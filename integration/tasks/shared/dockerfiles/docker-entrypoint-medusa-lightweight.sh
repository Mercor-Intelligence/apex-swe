#!/usr/bin/env bash
set -euo pipefail

# Defaults if not passed from compose
: "${POSTGRES_DB:=medusa-store}"
: "${POSTGRES_USER:=postgres}"
: "${POSTGRES_PASSWORD:=postgres}"
: "${DATABASE_URL:=postgres://$POSTGRES_USER:$POSTGRES_PASSWORD@localhost:5432/$POSTGRES_DB}"
: "${REDIS_URL:=redis://localhost:6379}"
: "${ADMIN_EMAIL:=admin@example.com}"
: "${ADMIN_PASSWORD:=supersecret}"

echo "==> ensuring PGDATA at $PGDATA"
mkdir -p "$PGDATA"
chown -R postgres:postgres "$PGDATA"

# Initialize database if empty
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "==> initializing postgres data dir"
  su postgres -c "/usr/lib/postgresql/*/bin/initdb -D '$PGDATA' -U postgres"
fi

# Start Postgres
echo "==> starting postgres"
su postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D '$PGDATA' -o \"-c listen_addresses='*'\" -w start"

# Create DB/user and set password if needed
echo "==> configuring postgres role/db"
su postgres -c "/usr/lib/postgresql/*/bin/psql -v ON_ERROR_STOP=1 <<'SQL'
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'postgres') THEN
    CREATE ROLE postgres WITH LOGIN SUPERUSER PASSWORD '${POSTGRES_PASSWORD}';
  ELSE
    ALTER ROLE postgres WITH PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END
\$\$;
SQL"

# Create database separately (CREATE DATABASE cannot be in a DO block)
echo "==> creating database if needed"
su postgres -c "/usr/lib/postgresql/*/bin/psql -tc \"SELECT 1 FROM pg_database WHERE datname = '${POSTGRES_DB}'\" | grep -q 1 || /usr/lib/postgresql/*/bin/psql -c 'CREATE DATABASE \"${POSTGRES_DB}\"'"

# Start Redis (foreground in background)
echo "==> starting redis"
redis-server --daemonize no --save "" --appendonly no &

# Move to app dir
cd /server

# Fix SSL issues by disabling DB SSL in medusa config if not already done
# (idempotent: only inject once)
if ! grep -q "databaseDriverOptions" medusa-config.ts 2>/dev/null; then
  echo "==> patching medusa-config.ts to disable DB SSL"
  node -e "let f='medusa-config.ts', s=require('fs').readFileSync(f,'utf8'); s=s.replace(/projectConfig:\\s*{/, m=>m+'\n    databaseDriverOptions: { ssl: false, sslmode: \"disable\" },'); require('fs').writeFileSync(f,s)"
fi

# Export URLs for medusa CLI
export DATABASE_URL REDIS_URL NODE_ENV=${NODE_ENV:-development}

echo "==> running migrations"
npx medusa db:migrate

# Create admin user (idempotent - will not fail if user already exists)
echo "==> creating admin user ${ADMIN_EMAIL}"
npx medusa user -e "$ADMIN_EMAIL" -p "$ADMIN_PASSWORD" 2>&1 | grep -v "User with email.*already exists" || \
  echo "==> admin user created or already exists"

echo "==> starting medusa dev server"
yarn dev &
MEDUSA_PID=$!

# Wait for Medusa to be ready
echo "==> waiting for Medusa to be ready..."
for i in {1..60}; do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:9000/health | grep -q "200"; then
    echo "==> Medusa is ready!"
    break
  fi
  echo "Waiting for Medusa... ($i/60)"
  sleep 2
done

# Create JWT token by authenticating
echo "==> Creating JWT token..."
JWT_RESPONSE=$(curl -s -X POST 'http://localhost:9000/auth/user/emailpass' \
  -H 'Content-Type: application/json' \
  --data-raw "{
    \"email\": \"${ADMIN_EMAIL}\",
    \"password\": \"${ADMIN_PASSWORD}\"
  }")

JWT_TOKEN=$(echo "$JWT_RESPONSE" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)

if [ -n "$JWT_TOKEN" ] && [ "$JWT_TOKEN" != "null" ]; then
  echo "==> JWT token created successfully"
  
  # Create publishable API key
  echo "==> Creating publishable API key..."
  API_KEY_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/api-keys' \
    -H "Authorization: Bearer $JWT_TOKEN" \
    -H 'Content-Type: application/json' \
    --data-raw '{
      "title": "Storefront Key",
      "type": "publishable"
    }')
  
  PUBLISHABLE_KEY=$(echo "$API_KEY_RESPONSE" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
  API_KEY_ID=$(echo "$API_KEY_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
  
  if [ -n "$PUBLISHABLE_KEY" ] && [ "$PUBLISHABLE_KEY" != "null" ]; then
    echo "==> Publishable API key created: $PUBLISHABLE_KEY (ID: $API_KEY_ID)"
    
    # Fetch sales channels
    echo "==> Fetching sales channels..."
    SALES_CHANNELS_RESPONSE=$(curl -s 'http://localhost:9000/admin/sales-channels' \
      -H "Authorization: Bearer $JWT_TOKEN")
    
    # Extract the first sales channel ID
    SALES_CHANNEL_ID=$(echo "$SALES_CHANNELS_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
    
    if [ -n "$SALES_CHANNEL_ID" ] && [ "$SALES_CHANNEL_ID" != "null" ]; then
      echo "==> Found sales channel: $SALES_CHANNEL_ID"
      
      # Attach publishable key to sales channel
      echo "==> Attaching publishable key to sales channel..."
      ATTACH_RESPONSE=$(curl -s -X POST "http://localhost:9000/admin/api-keys/$API_KEY_ID/sales-channels" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H 'Content-Type: application/json' \
        --data-raw "{
          \"add\": [\"$SALES_CHANNEL_ID\"]
        }")
      
      echo "==> Publishable key attached to sales channel successfully"
    else
      echo "Warning: No sales channels found to attach publishable key"
      echo "Sales channels response: $SALES_CHANNELS_RESPONSE"
    fi
    
    # Add Medusa config to MCP config file
    if [ -d "/config" ]; then
      echo "==> Adding Medusa configuration to MCP config..."
      echo "export MEDUSA_BACKEND_URL=http://medusa:9000" >> /config/mcp-config.txt
      echo "export PUBLISHABLE_KEY=$PUBLISHABLE_KEY" >> /config/mcp-config.txt
      echo "export MEDUSA_USERNAME=$ADMIN_EMAIL" >> /config/mcp-config.txt
      echo "export MEDUSA_PASSWORD=$ADMIN_PASSWORD" >> /config/mcp-config.txt
      echo "==> Medusa config added to MCP config"
      echo "MEDUSA_BACKEND_URL: http://medusa:9000"
      echo "PUBLISHABLE_KEY: $PUBLISHABLE_KEY"
      echo "MEDUSA_USERNAME: $ADMIN_EMAIL"
      echo "MEDUSA_PASSWORD: $ADMIN_PASSWORD"
    else
      echo "No /config directory found, skipping MCP config update"
      echo "Generated Publishable Key: $PUBLISHABLE_KEY"
    fi
  else
    echo "Failed to create publishable API key"
    echo "Response: $API_KEY_RESPONSE"
  fi
else
  echo "Failed to create JWT token"
  echo "Response: $JWT_RESPONSE"
fi

# Always run default seed first to create infrastructure (regions, service zones, shipping options)
echo "==> Running default Medusa seed to create infrastructure..."
yarn seed
echo "==> Default seed completed"

# Seed custom data from JSON file if it exists
if [ -f "/data/medusa-seed-data.json" ] && [ -n "$JWT_TOKEN" ] && [ "$JWT_TOKEN" != "null" ]; then
  echo "==> Found custom seed data file, adding custom data on top..."
  
  # Read the JSON file
  SEED_DATA=$(cat /data/medusa-seed-data.json)
  
  # Create categories first (products depend on them)
  echo "==> Seeding categories..."
  node -e "
    const fs = require('fs');
    try {
      const seedData = JSON.parse(fs.readFileSync('/data/medusa-seed-data.json', 'utf-8'));
      const categories = seedData.categories || [];
      if (categories.length === 0) {
        console.error('No categories to seed');
      } else {
        categories.forEach(category => {
          console.log(JSON.stringify(category));
        });
      }
    } catch (e) {
      console.error('Error reading categories:', e.message);
    }
  " | while IFS= read -r category; do
    if [ -n "$category" ] && [ "$category" != "No categories to seed" ]; then
      echo "Creating category..."
      CATEGORY_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/product-categories' \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H 'Content-Type: application/json' \
        --data-raw "$category" || echo '{"error": "curl failed"}')
      
      CATEGORY_ID=$(echo "$CATEGORY_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
      if [ -n "$CATEGORY_ID" ] && [ "$CATEGORY_ID" != "null" ]; then
        echo "Created category: $CATEGORY_ID"
      else
        echo "Warning: Failed to create category"
        echo "Response: $CATEGORY_RESPONSE"
      fi
    fi
  done
  echo "==> Categories seeding completed"
  
  # Get region ID for products and orders
  echo "==> Fetching region information..."
  REGION_RESPONSE=$(curl -s 'http://localhost:9000/admin/regions' \
    -H "Authorization: Bearer $JWT_TOKEN")
  REGION_ID=$(echo "$REGION_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  
  # Create a default region if none exists
  if [ -z "$REGION_ID" ] || [ "$REGION_ID" = "null" ]; then
    echo "==> No regions found, creating default US region..."
    CREATE_REGION_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/regions' \
      -H "Authorization: Bearer $JWT_TOKEN" \
      -H 'Content-Type: application/json' \
      --data-raw '{
        "name": "United States",
        "currency_code": "usd",
        "countries": ["us"],
        "payment_providers": ["pp_system_default"],
        "is_tax_inclusive": false
      }')
    REGION_ID=$(echo "$CREATE_REGION_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
    echo "Created region: $REGION_ID"
  fi
  
  echo "Using region: $REGION_ID"
  
  # Create products (shipping options created by default seed)
  echo "==> Seeding products..."
  node -e "
    const fs = require('fs');
    // Only these variant fields are accepted by the Medusa POST /admin/products API.
    // Any extra fields (e.g., inventory_quantity) cause a 400 error and crash the container.
    const VALID_VARIANT_FIELDS = new Set(['title', 'sku', 'prices', 'options', 'manage_inventory', 'allow_backorder']);
    try {
      const seedData = JSON.parse(fs.readFileSync('/data/medusa-seed-data.json', 'utf-8'));
      const products = seedData.products || [];
      if (products.length === 0) {
        console.error('No products to seed');
      } else {
        products.forEach(product => {
          // Remove 'handle' from product level (can cause duplicate conflicts)
          delete product.handle;
          // Sanitize variants: strip invalid fields, add manage_inventory: false
          if (product.variants) {
            product.variants = product.variants.map(variant => {
              const clean = {};
              for (const [key, val] of Object.entries(variant)) {
                if (VALID_VARIANT_FIELDS.has(key)) {
                  clean[key] = val;
                } else {
                  console.error('Stripping invalid variant field: ' + key);
                }
              }
              clean.manage_inventory = false;
              return clean;
            });
          }
          console.log(JSON.stringify(product));
        });
      }
    } catch (e) {
      console.error('Error reading products:', e.message);
    }
  " | while IFS= read -r product; do
    if [ -n "$product" ] && [ "$product" != "No products to seed" ]; then
      PRODUCT_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/products' \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H 'Content-Type: application/json' \
        --data-raw "$product" || echo '{"error": "curl failed"}')
      
      PRODUCT_ID=$(echo "$PRODUCT_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
      if [ -n "$PRODUCT_ID" ] && [ "$PRODUCT_ID" != "null" ]; then
        echo "Created product: $PRODUCT_ID"
      else
        echo "Warning: Failed to create product"
      fi
    fi
  done
  echo "==> Products seeding completed"
  
  # Create customers
  echo "==> Seeding customers..."
  node -e "
    const fs = require('fs');
    try {
      const seedData = JSON.parse(fs.readFileSync('/data/medusa-seed-data.json', 'utf-8'));
      const customers = seedData.customers || [];
      if (customers.length === 0) {
        console.error('No customers to seed');
      } else {
        customers.forEach(customer => {
          console.log(JSON.stringify(customer));
        });
      }
    } catch (e) {
      console.error('Error reading customers:', e.message);
    }
  " | while IFS= read -r customer; do
    if [ -n "$customer" ] && [ "$customer" != "No customers to seed" ]; then
      CUSTOMER_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/customers' \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H 'Content-Type: application/json' \
        --data-raw "$customer" || echo '{"error": "curl failed"}')
      
      CUSTOMER_ID=$(echo "$CUSTOMER_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
      if [ -n "$CUSTOMER_ID" ] && [ "$CUSTOMER_ID" != "null" ]; then
        echo "Created customer: $CUSTOMER_ID"
      else
        echo "Warning: Failed to create customer"
      fi
    fi
  done
  echo "==> Customers seeding completed"
  
  # Create orders (using draft orders API)
  echo "==> Seeding orders..."
  
  # First, get all products and customers to map IDs - no artificial limits
  PRODUCTS_RESPONSE=$(curl -s 'http://localhost:9000/admin/products?limit=10000' \
    -H "Authorization: Bearer $JWT_TOKEN")
  
  CUSTOMERS_RESPONSE=$(curl -s 'http://localhost:9000/admin/customers?limit=10000' \
    -H "Authorization: Bearer $JWT_TOKEN")
  
  SHIPPING_OPTIONS_RESPONSE=$(curl -s 'http://localhost:9000/admin/shipping-options' \
    -H "Authorization: Bearer $JWT_TOKEN")
  
  echo "Checking for shipping options..."
  
  # Use Node.js to process orders with ID mapping
  node -e "
    const seedData = JSON.parse(require('fs').readFileSync('/data/medusa-seed-data.json', 'utf-8'));
    const orders = seedData.orders || [];
    const products = JSON.parse(\`$PRODUCTS_RESPONSE\`).products || [];
    const customers = JSON.parse(\`$CUSTOMERS_RESPONSE\`).customers || [];
    const shippingOptionsData = JSON.parse(\`$SHIPPING_OPTIONS_RESPONSE\`);
    const shippingOptions = shippingOptionsData.shipping_options || [];
    const regionId = '$REGION_ID';
    
    console.error('Found ' + products.length + ' products');
    console.error('Found ' + customers.length + ' customers');
    console.error('Found ' + shippingOptions.length + ' shipping options');
    console.error('Using region: ' + regionId);
    
    // Debug: Check product variants
    if (products.length > 0 && products[0].variants) {
      console.error('First product has ' + products[0].variants.length + ' variants');
      console.error('First variant ID: ' + products[0].variants[0].id);
    }
    
    if (orders.length === 0) {
      console.log('No orders to seed');
      process.exit(0);
    }
    
    orders.forEach((order, idx) => {
      try {
        // Map customer email to ID
        const customer = customers.find(c => c.email === order.customer_email);
        if (!customer && !order.email) {
          console.error(\`Order \${idx + 1}: No customer found for \${order.customer_email}\`);
          return;
        }
        
        // Map product references to variant IDs
        const mappedItems = [];
        for (const item of (order.items || [])) {
          let variantId = item.variant_id;
          
          // If variant_id is provided, use it directly
          if (!variantId && item.product_title) {
            // Find product by title
            const product = products.find(p => p.title === item.product_title);
            if (product && product.variants && product.variants.length > 0) {
              // Use first variant or find by SKU if provided
              if (item.variant_sku) {
                const variant = product.variants.find(v => v.sku === item.variant_sku);
                variantId = variant?.id;
              } else {
                variantId = product.variants[0].id;
              }
            }
          }
          
          if (variantId) {
            mappedItems.push({
              variant_id: variantId,
              quantity: item.quantity || 1
            });
          }
        }
        
        if (mappedItems.length === 0) {
          console.error(\`Order \${idx + 1}: No valid items found\`);
          return;
        }
        
        // Get shipping option for the region, or use first available
        let shippingOption = shippingOptions.find(opt => opt.region_id === regionId);
        if (!shippingOption && shippingOptions.length > 0) {
          shippingOption = shippingOptions[0];
          console.error(\`Order \${idx + 1}: Using shipping option from different region\`);
        }
        if (!shippingOption) {
          console.error(\`Order \${idx + 1}: No shipping options available\`);
          return;
        }
        
        // Build the order data
        const orderData = {
          email: order.email || customer.email,
          region_id: regionId,
          currency_code: 'usd',
          items: mappedItems,
          shipping_methods: [{
            name: shippingOption.name || 'Standard Shipping',
            shipping_option_id: shippingOption.id,
            amount: shippingOption.amount || 1000
          }],
          shipping_address: order.shipping_address || {
            first_name: customer?.first_name || 'John',
            last_name: customer?.last_name || 'Doe',
            address_1: '123 Main St',
            city: 'New York',
            country_code: 'us',
            province: 'NY',
            postal_code: '10001',
            phone: customer?.phone || '+1234567890'
          },
          billing_address: order.billing_address || order.shipping_address || {
            first_name: customer?.first_name || 'John',
            last_name: customer?.last_name || 'Doe',
            address_1: '123 Main St',
            city: 'New York',
            country_code: 'us',
            province: 'NY',
            postal_code: '10001',
            phone: customer?.phone || '+1234567890'
          }
        };
        
        console.log(JSON.stringify(orderData));
      } catch (e) {
        console.error(\`Order \${idx + 1} error: \${e.message}\`);
      }
    });
  " | while IFS= read -r order_data; do
    if [ -n "$order_data" ] && [ "$order_data" != "No orders to seed" ]; then
      # Create draft order
      DRAFT_ORDER_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/draft-orders' \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H 'Content-Type: application/json' \
        --data-raw "$order_data" || echo '{"error": "curl failed"}')
      
      DRAFT_ORDER_ID=$(echo "$DRAFT_ORDER_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
      
      if [ -n "$DRAFT_ORDER_ID" ] && [ "$DRAFT_ORDER_ID" != "null" ]; then
        echo "Created draft order: $DRAFT_ORDER_ID"
        
        # Step 1: Convert draft order to order
        CONVERT_RESPONSE=$(curl -s -X POST "http://localhost:9000/admin/draft-orders/$DRAFT_ORDER_ID/convert-to-order" \
          -H "Authorization: Bearer $JWT_TOKEN" \
          -H 'Content-Type: application/json' || echo '{"error": "curl failed"}')
        
        ORDER_ID=$(echo "$CONVERT_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
        if [ -n "$ORDER_ID" ] && [ "$ORDER_ID" != "null" ]; then
          echo "Converted to order: $ORDER_ID"
          
          # Step 2: Complete the order (no body required)
          COMPLETE_RESPONSE=$(curl -s -X POST "http://localhost:9000/admin/orders/$ORDER_ID/complete" \
            -H "Authorization: Bearer $JWT_TOKEN" \
            -H 'Content-Type: application/json' || echo '{"error": "curl failed"}')
          
          COMPLETED_ORDER_ID=$(echo "$COMPLETE_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
          if [ -n "$COMPLETED_ORDER_ID" ] && [ "$COMPLETED_ORDER_ID" != "null" ]; then
            echo "Completed order: $COMPLETED_ORDER_ID"
          else
            echo "Warning: Failed to complete order $ORDER_ID"
          fi
        else
          echo "Warning: Failed to convert draft order $DRAFT_ORDER_ID to order"
        fi
      else
        echo "Warning: Failed to create draft order"
      fi
    fi
  done
  echo "==> Orders seeding completed"
  
  # Create draft orders from "carts" data (abandoned carts - NOT converted to orders)
  echo "==> Seeding abandoned carts (draft orders)..."
  
  CARTS_COUNT=$(echo "$SEED_DATA" | jq '.carts | length // 0')
  if [ "$CARTS_COUNT" -gt 0 ]; then
    node -e "
      const seedData = JSON.parse(require('fs').readFileSync('/data/medusa-seed-data.json', 'utf-8'));
      const carts = seedData.carts || [];
      carts.forEach((cart, idx) => {
        // Output cart data as JSON for processing
        console.log(JSON.stringify({
          email: cart.email,
          completed_at: cart.completed_at || null,
          items: cart.items || []
        }));
      });
    " | while IFS= read -r cart_json; do
      if [ -n "$cart_json" ]; then
        CART_EMAIL=$(echo "$cart_json" | jq -r '.email')
        
        # Create a draft order for this abandoned cart
        DRAFT_ORDER_PAYLOAD=$(cat <<DRAFT_EOF
{
  "email": "${CART_EMAIL}",
  "region_id": "${REGION_ID}",
  "items": [],
  "shipping_methods": []
}
DRAFT_EOF
)
        
        DRAFT_RESPONSE=$(curl -s -X POST 'http://localhost:9000/admin/draft-orders' \
          -H "Authorization: Bearer $JWT_TOKEN" \
          -H 'Content-Type: application/json' \
          --data-raw "$DRAFT_ORDER_PAYLOAD" || echo '{"error": "curl failed"}')
        
        DRAFT_ID=$(echo "$DRAFT_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
        if [ -n "$DRAFT_ID" ] && [ "$DRAFT_ID" != "null" ]; then
          echo "Created abandoned cart (draft order) for $CART_EMAIL: $DRAFT_ID"
        else
          echo "Warning: Failed to create draft order for $CART_EMAIL"
        fi
      fi
    done
  else
    echo "No carts to seed"
  fi
  echo "==> Abandoned carts seeding completed"
  
  echo "==> Custom data seeding completed!"
  touch /config/.medusa-seed-complete
else
  if [ ! -f "/data/medusa-seed-data.json" ]; then
    echo "==> No custom seed data file found at /data/medusa-seed-data.json, skipping custom seeding"
  fi
  touch /config/.medusa-seed-complete
fi

# Wait for the Medusa server process
wait $MEDUSA_PID
