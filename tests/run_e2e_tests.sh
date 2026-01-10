#!/bin/bash
# E2E Test Runner with Failure Reporting
# Usage: ./run_e2e_tests.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=================================================="
echo "  E2E Test Runner - Real Tests Only"
echo "=================================================="
echo ""

# Activate virtual environment
source .venv/bin/activate

# Load E2E environment variables
set -a
source .env.e2e
set +a

# Timestamp for report
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
REPORT_FILE="e2e_test_report_${TIMESTAMP}.txt"

echo "Report will be saved to: $REPORT_FILE"
echo ""

# Function to run tests and capture results
run_test_suite() {
    local test_file=$1
    local test_name=$2

    echo -e "${YELLOW}Running: $test_name${NC}"
    echo "=========================================="

    if pytest "$test_file" -v --tb=short 2>&1 | tee -a "$REPORT_FILE"; then
        echo -e "${GREEN}✅ $test_name: PASSED${NC}"
        return 0
    else
        echo -e "${RED}❌ $test_name: FAILED${NC}"
        return 1
    fi
}

# Initialize counters
TOTAL_SUITES=0
PASSED_SUITES=0
FAILED_SUITES=0

# Write header to report
cat > "$REPORT_FILE" << EOF
================================================
E2E Test Report
================================================
Date: $(date)
Environment: E2E Testing
================================================

EOF

# Run all E2E test suites
echo "Running Real E2E Test Suites..."
echo ""

# Admin Escalation & Information Guardian Tests
TOTAL_SUITES=$((TOTAL_SUITES + 1))
if run_test_suite "tests/e2e/test_admin_escalation_live.py" "Admin Escalation & Info Guardian"; then
    PASSED_SUITES=$((PASSED_SUITES + 1))
else
    FAILED_SUITES=$((FAILED_SUITES + 1))
fi
echo ""

# Knowledge Creation Tests (if they exist and work)
if [ -f "tests/e2e/test_knowledge_creation_live.py" ]; then
    TOTAL_SUITES=$((TOTAL_SUITES + 1))
    echo -e "${YELLOW}⚠️  Knowledge Creation tests exist but may need fixes${NC}"
    if run_test_suite "tests/e2e/test_knowledge_creation_live.py" "Knowledge Creation"; then
        PASSED_SUITES=$((PASSED_SUITES + 1))
    else
        FAILED_SUITES=$((FAILED_SUITES + 1))
    fi
    echo ""
fi

# Bot Q&A Tests (if they exist)
if [ -f "tests/e2e/test_bot_qa_live.py" ]; then
    TOTAL_SUITES=$((TOTAL_SUITES + 1))
    if run_test_suite "tests/e2e/test_bot_qa_live.py" "Bot Q&A"; then
        PASSED_SUITES=$((PASSED_SUITES + 1))
    else
        FAILED_SUITES=$((FAILED_SUITES + 1))
    fi
    echo ""
fi

# Document Ingestion Tests (if they exist)
if [ -f "tests/e2e/test_doc_ingestion_live.py" ]; then
    TOTAL_SUITES=$((TOTAL_SUITES + 1))
    if run_test_suite "tests/e2e/test_doc_ingestion_live.py" "Document Ingestion"; then
        PASSED_SUITES=$((PASSED_SUITES + 1))
    else
        FAILED_SUITES=$((FAILED_SUITES + 1))
    fi
    echo ""
fi

# Generate summary
cat >> "$REPORT_FILE" << EOF

================================================
Summary
================================================
Total Test Suites: $TOTAL_SUITES
Passed: $PASSED_SUITES
Failed: $FAILED_SUITES
Success Rate: $(( PASSED_SUITES * 100 / TOTAL_SUITES ))%
================================================

EOF

echo "=================================================="
echo "  E2E Test Summary"
echo "=================================================="
echo -e "Total Suites: $TOTAL_SUITES"
echo -e "${GREEN}Passed: $PASSED_SUITES${NC}"
echo -e "${RED}Failed: $FAILED_SUITES${NC}"
echo -e "Success Rate: $(( PASSED_SUITES * 100 / TOTAL_SUITES ))%"
echo ""
echo "Full report saved to: $REPORT_FILE"
echo "=================================================="

# Report on what's NOT tested
echo ""
echo "⚠️  Features NOT Tested E2E (Using Mocks):"
echo "  - Knowledge Creation (/create-knowledge)"
echo "  - Document Ingestion (/ingest-doc)"
echo "  - Feedback Quality Score Updates"
echo "  - Thread to Knowledge Conversion"
echo "  - Document Creation (/create-doc)"
echo ""
echo "See tests/e2e/E2E_TEST_REQUIREMENTS.md for details"
echo ""

# Exit with failure if any tests failed
if [ $FAILED_SUITES -gt 0 ]; then
    echo -e "${RED}⚠️  Some E2E tests failed! Review the report above.${NC}"
    exit 1
else
    echo -e "${GREEN}✅ All E2E tests passed!${NC}"
    exit 0
fi
