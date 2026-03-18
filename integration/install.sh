#!/bin/bash
#
# APEX SWE Harness - One-Command Installation Script
#
# This script installs all required components for running evaluations.
# Usage:
#   ./install.sh              # Install with prompts
#   ./install.sh --yes        # Install without prompts
#   ./install.sh --dev        # Install with development dependencies
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
AUTO_YES=false
DEV_MODE=false

for arg in "$@"; do
    case $arg in
        --yes|-y)
            AUTO_YES=true
            ;;
        --dev|-d)
            DEV_MODE=true
            ;;
        --help|-h)
            echo "APEX SWE Harness Installation Script"
            echo ""
            echo "Usage: ./install.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --yes, -y       Skip confirmation prompts"
            echo "  --dev, -d       Install development dependencies"
            echo "  --help, -h      Show this help message"
            echo ""
            exit 0
            ;;
    esac
done

# Helper functions
print_header() {
    echo -e "${BLUE}======================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}======================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    print_header "Checking Prerequisites"
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION found"
    
    # Check Python version >= 3.10
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)
    if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
        print_error "Python 3.10 or higher is required (found $PYTHON_VERSION)"
        exit 1
    fi
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        print_warning "Docker is not installed or not in PATH"
        print_info "Docker is required to run evaluations"
        if [ "$AUTO_YES" = false ]; then
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    else
        if docker ps &> /dev/null; then
            print_success "Docker is running"
        else
            print_warning "Docker is installed but not running"
            print_info "Please start Docker before running evaluations"
        fi
    fi
    
    # Check Git
    if ! command -v git &> /dev/null; then
        print_warning "Git is not installed"
    else
        print_success "Git found"
    fi
    
    echo ""
}

# Create virtual environment
setup_venv() {
    print_header "Setting Up Virtual Environment"
    
    if [ -d "$SCRIPT_DIR/venv" ]; then
        print_warning "Virtual environment already exists at $SCRIPT_DIR/venv"
        if [ "$AUTO_YES" = false ]; then
            read -p "Recreate it? (y/N) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                rm -rf "$SCRIPT_DIR/venv"
            else
                print_info "Using existing virtual environment"
                source "$SCRIPT_DIR/venv/bin/activate"
                print_success "Virtual environment activated"
                echo ""
                return 0
            fi
        fi
    fi
    
    if [ ! -d "$SCRIPT_DIR/venv" ]; then
        python3 -m venv "$SCRIPT_DIR/venv"
        print_success "Virtual environment created"
    fi
    
    # Activate virtual environment
    source "$SCRIPT_DIR/venv/bin/activate"
    print_success "Virtual environment activated"
    
    # Upgrade pip
    print_info "Upgrading pip..."
    pip install --upgrade pip -q
    print_success "pip upgraded"
    
    echo ""
}

# Install APEX SWE Harness
install_harness() {
    print_header "Installing APEX SWE Harness"
    
    cd "$SCRIPT_DIR"
    
    if [ "$DEV_MODE" = true ]; then
        print_info "Installing with development dependencies..."
        pip install -e ".[dev]" -q
    else
        pip install -e . -q
    fi
    
    print_success "APEX SWE Harness installed"
    
    cd "$SCRIPT_DIR"
    echo ""
}

# Verify installation
verify_installation() {
    print_header "Verifying Installation"
    
    local all_good=true
    
    # Check apx command
    if command -v apx &> /dev/null; then
        print_success "apx command: $(which apx)"
    else
        print_error "apx command not found"
        all_good=false
    fi
    
    # Check Python packages can be imported (from integration directory)
    cd "$SCRIPT_DIR"
    if python3 -c "from src.harness import executor" 2>/dev/null; then
        print_success "Harness modules importable"
    else
        print_error "Harness modules not importable"
        all_good=false
    fi
    cd "$SCRIPT_DIR"
    
    # Check that tasks directory exists
    if [ -d "$SCRIPT_DIR/tasks" ]; then
        task_count=$(find "$SCRIPT_DIR/tasks" -maxdepth 1 -type d | wc -l)
        print_success "Tasks directory found with $((task_count - 1)) tasks"
    else
        print_warning "Tasks directory not found at integration/tasks"
    fi
    
    echo ""
    
    if [ "$all_good" = true ]; then
        print_success "All verifications passed!"
        return 0
    else
        print_error "Some verifications failed"
        return 1
    fi
}

# Show next steps
show_next_steps() {
    print_header "Installation Complete!"
    
    echo ""
    echo -e "${GREEN}Next Steps:${NC}"
    echo ""
    echo "1. Activate the virtual environment:"
    echo -e "   ${BLUE}source venv/bin/activate${NC}"
    echo ""
    echo "2. Set up API keys (in ~/.bashrc or export manually):"
    echo -e "   ${BLUE}export ANTHROPIC_API_KEY='your-key'${NC}     # For Claude models"
    echo -e "   ${BLUE}export OPENAI_API_KEY='your-key'${NC}        # For GPT models"
    echo -e "   ${BLUE}export GOOGLE_API_KEY='your-key'${NC}        # For Gemini models"
    echo -e "   ${BLUE}export XAI_API_KEY='your-key'${NC}           # For xAI Grok"
    echo -e "   ${BLUE}export FIREWORKS_API_KEY='your-key'${NC}     # For DeepSeek/Qwen/Kimi"
    echo ""
    echo "3. Verify the CLI works:"
    echo -e "   ${BLUE}apx --help${NC}"
    echo -e "   ${BLUE}apx list-models${NC}"
    echo -e "   ${BLUE}apx list-tasks${NC}"
    echo ""
    echo "4. Run your first evaluation:"
    echo -e "   ${BLUE}cd integration${NC}"
    echo -e "   ${BLUE}apx run my-experiment --tasks 1-aws-s3-snapshots --models claude-sonnet-4-20250514 --n-trials 1${NC}"
    echo ""
    echo "📚 Documentation: See integration/README.md for full documentation"
    echo ""
}

# Main installation flow
main() {
    clear
    echo -e "${BLUE}"
    echo "╔════════════════════════════════════════════╗"
    echo "║   APEX SWE Harness Installation Script    ║"
    echo "╚════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    
    if [ "$AUTO_YES" = false ]; then
        echo "This script will:"
        echo "  1. Check prerequisites (Python 3.10+, Docker)"
        echo "  2. Create a virtual environment"
        echo "  3. Install APEX SWE Harness (apx command)"
        echo ""
        read -p "Continue? (Y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Nn]$ ]]; then
            echo "Installation cancelled."
            exit 0
        fi
        echo ""
    fi
    
    # Run installation steps
    check_prerequisites
    setup_venv
    install_harness
    
    # Verify
    if verify_installation; then
        show_next_steps
        exit 0
    else
        echo ""
        print_error "Installation completed with errors"
        echo ""
        print_info "Try running the following commands manually:"
        echo "  source venv/bin/activate"
        echo "  cd integration && pip install -e ."
        echo ""
        exit 1
    fi
}

# Run main
main
