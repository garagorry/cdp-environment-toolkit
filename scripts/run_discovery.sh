#!/bin/bash
# CDP Environment Toolkit — discover wrapper

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       CDP Environment Toolkit (cdp-discover discover)           ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ -z "$1" ]; then
    echo -e "${RED}Error: Environment name required${NC}"
    echo ""
    echo "Usage: $0 <environment-name> [discover options...]"
    echo ""
    echo "Examples:"
    echo "  $0 my-cdp-env"
    echo "  $0 my-env --profile production"
    echo "  $0 my-env --include-services cde cdw cai"
    exit 1
fi

ENVIRONMENT_NAME="$1"
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if ! command -v cdp &> /dev/null; then
    echo -e "${YELLOW}⚠️  CDP CLI not found in PATH${NC}"
    echo "Activate your CDP CLI environment, then retry."
    read -p "Press Enter to continue anyway, or Ctrl+C to abort..."
fi

echo -e "${BLUE}🔍 Verifying CDP CLI...${NC}"
if cdp --version &> /dev/null; then
    echo -e "${GREEN}✅ CDP CLI: $(cdp --version 2>&1 | head -1)${NC}"
else
    echo -e "${RED}❌ CDP CLI verification failed${NC}"
    exit 1
fi

if ! command -v cdp-discover &> /dev/null; then
    echo -e "${YELLOW}⚠️  cdp-discover not in PATH; using python -m cdp_discover${NC}"
    RUN=(python3 -m cdp_discover discover)
else
    RUN=(cdp-discover discover)
fi

cd "$REPO_ROOT"
echo ""
echo -e "${BLUE}🚀 Discovering environment: ${GREEN}${ENVIRONMENT_NAME}${NC}"
echo ""

"${RUN[@]}" --environment-name "$ENVIRONMENT_NAME" "$@"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Discovery completed. Run generate next:${NC}"
    echo "  cdp-discover generate -d <output-dir> -c aws --no-prompt"
else
    echo -e "${RED}❌ Discovery failed (exit $EXIT_CODE). Try --debug.${NC}"
fi

exit $EXIT_CODE
