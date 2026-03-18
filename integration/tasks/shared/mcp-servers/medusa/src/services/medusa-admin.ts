import Medusa from "@medusajs/js-sdk";
import { config } from "dotenv";
import { z, ZodTypeAny } from "zod";
import adminJson from "../oas/admin.json";
import { SdkRequestType, Parameter } from "../types/admin-json";
import { defineTool, InferToolHandlerInput } from "../utils/define-tools";

config();

const MEDUSA_BACKEND_URL =
    process.env.MEDUSA_BACKEND_URL ?? "http://localhost:9000";

const MEDUSA_USERNAME = process.env.MEDUSA_USERNAME ?? "medusa_user";
const MEDUSA_PASSWORD = process.env.MEDUSA_PASSWORD ?? "medusa_pass";

export default class MedusaAdminService {
    sdk: Medusa;
    adminToken = "";
    constructor() {
        this.sdk = new Medusa({
            baseUrl: MEDUSA_BACKEND_URL,
            debug: process.env.NODE_ENV === "development",
            publishableKey: process.env.NEXT_PUBLIC_MEDUSA_PUBLISHABLE_KEY,
            auth: {
                type: "jwt"
            }
        });
    }

    async init(): Promise<void> {
        const res = await this.sdk.auth.login("user", "emailpass", {
            email: MEDUSA_USERNAME,
            password: MEDUSA_PASSWORD
        });
        this.adminToken = res.toString();
    }

    wrapPath(refPath: string, refFunction: SdkRequestType) {
        return defineTool((z) => {
            let name;
            let description;
            let parameters: Parameter[] = [];
            let method = "get";
            if ("get" in refFunction) {
                method = "get";
                name = refFunction.get.operationId;
                description = refFunction.get.description;
                parameters = (refFunction.get.parameters ?? "") as any;
            } else if ("post" in refFunction) {
                method = "post";
                name = refFunction.post.operationId;
                description = refFunction.post.description;
                parameters = refFunction.post.parameters ?? [];
            } else if ("delete" in refFunction) {
                method = "delete";
                name = (refFunction.delete as any).operationId;
                description = (refFunction.delete as any).description;
                parameters = (refFunction.delete as any).parameters ?? [];
            }
            if (!name) {
                throw new Error("No name found for path: " + refPath);
            }
            const paramSchema = parameters
                .filter((p) => p.in != "header")
                .reduce((acc, param) => {
                    switch (param.schema.type) {
                        case "string":
                            acc[param.name] = z.string().optional();
                            break;
                        case "number":
                            acc[param.name] = z.number().optional();
                            break;
                        case "boolean":
                            acc[param.name] = z.boolean().optional();
                            break;
                        case "array":
                            acc[param.name] = z
                                .array(z.string())
                                .optional();
                            break;
                        case "object":
                            acc[param.name] = z.object({}).optional();
                            break;
                        default:
                            acc[param.name] = z.string().optional();
                    }
                    return acc;
                }, {} as any);

            // For POST/DELETE, add common body field validators
            // Use z.unknown() for flexibility since different endpoints expect different types
            const bodySchema = method !== "get" ? {
                title: z.string().optional(),
                description: z.string().optional(),
                subtitle: z.string().optional(),
                handle: z.string().optional(),
                status: z.string().optional(),
                sku: z.string().optional(),
                options: z.unknown().optional(), // Can be array or object depending on endpoint
                variants: z.unknown().optional(),
                images: z.unknown().optional(),
                prices: z.unknown().optional(),
                metadata: z.unknown().optional(),
                tags: z.unknown().optional(),
                type: z.unknown().optional(),
                collection_id: z.string().optional(),
                categories: z.unknown().optional(),
                manage_inventory: z.boolean().optional(),
                allow_backorder: z.boolean().optional(),
                // Catch-all for other body fields
                ...Object.fromEntries(
                    ['weight', 'length', 'height', 'width', 'hs_code', 'mid_code', 
                     'material', 'origin_country', 'discountable', 'is_giftcard',
                     'thumbnail', 'external_id'].map(k => [k, z.unknown().optional()])
                )
            } : {};

            return {
                name: `Admin${name}`,
                description: `This tool helps store administors. ${description}`,
                inputSchema: {
                    ...paramSchema,
                    ...bodySchema
                },

                handler: async (
                    input: InferToolHandlerInput<any, ZodTypeAny>
                ): Promise<any> => {
                    const queryParamNames = (parameters || [])
                        .filter((p) => p.in === "query")
                        .map((p) => p.name);
                    
                    const pathParamNames = (parameters || [])
                        .filter((p) => p.in === "path")
                        .map((p) => p.name);

                    // Replace path parameters in URL
                    let finalPath = refPath;
                    for (const paramName of pathParamNames) {
                        const value = (input as any)[paramName];
                        if (value !== undefined && value !== null) {
                            finalPath = finalPath.replace(`{${paramName}}`, String(value));
                        }
                    }

                    const query = new URLSearchParams();
                    for (const name of queryParamNames) {
                        const value = (input as any)[name];
                        if (value === undefined || value === null) continue;
                        if (Array.isArray(value)) {
                            for (const v of value) query.append(name, String(v));
                        } else {
                            query.set(name, String(value));
                        }
                    }

                    // Build body from remaining inputs (exclude query/header/path params)
                    const body: Record<string, any> = {};
                    if (method !== "get") {
                        for (const [key, value] of Object.entries(input as any)) {
                            if (queryParamNames.includes(key)) continue;
                            if (pathParamNames.includes(key)) continue;
                            body[key] = value;
                        }
                    }

                    const response = await this.sdk.client.fetch(finalPath, {
                        method: method,
                        headers: {
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Authorization": `Bearer ${this.adminToken}`
                        },
                        // Always pass query if present; SDK will ignore if empty
                        query,
                        // Pass an object; SDK handles JSON encoding. Avoid double-stringify
                        ...(method === "get" ? {} : { body })
                    });
                    return response;
                }
            };
        });
    }

    defineTools(admin = adminJson): any[] {
        const paths = Object.entries(admin.paths) as [string, SdkRequestType][];
        const tools: any[] = [];
        
        for (const [path, refFunction] of paths) {
            const anyRef = refFunction as any;
            // Process each HTTP method separately, checking for operationId
            if (anyRef.get && anyRef.get.operationId) {
                tools.push(this.wrapPath(path, { get: anyRef.get } as any));
            }
            if (anyRef.post && anyRef.post.operationId) {
                tools.push(this.wrapPath(path, { post: anyRef.post } as any));
            }
            if (anyRef.delete && anyRef.delete.operationId) {
                tools.push(this.wrapPath(path, { delete: anyRef.delete } as any));
            }
        }
        
        return tools;
    }
}
