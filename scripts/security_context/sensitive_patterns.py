"""
Security patterns for detecting potential vulnerabilities in code changes.

This module defines regex patterns for pre-scanning code before LLM analysis,
and file sensitivity classifications for prioritizing security review focus.
"""

# Regex patterns for detecting security issues
# These run as a quick pre-scan before sending to Claude for deeper analysis

SECURITY_PATTERNS = {
    # CRITICAL: Credential exposure in logs or output
    'credential_logging': [
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*password',
        r'print\s*\([^)]*password',
        r'logging\.(info|debug|error|warning|critical)\s*\([^)]*password',
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*api_key',
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*api_token',
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*secret',
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*token(?!ize)',  # token but not tokenize
        r'logger\.(info|debug|error|warning|critical)\s*\([^)]*signing_secret',
    ],

    # CRITICAL: Hardcoded credentials
    'hardcoded_credentials': [
        r"password\s*=\s*[\"'][^\"']{4,}[\"']",        # password = "something"
        r"api_key\s*=\s*[\"'][^\"']{8,}[\"']",         # api_key = "something"
        r"api_token\s*=\s*[\"'][^\"']{8,}[\"']",       # api_token = "something"
        r"secret\s*=\s*[\"'][^\"']{8,}[\"']",          # secret = "something"
        r"token\s*=\s*[\"'][^\"']{10,}[\"']",         # token = "something"
        r"ANTHROPBC_API_KEY\s*=\s*[\"'][^\"']+[\"']",
        r"SLACK_BOT_TOKEN\s*=\s*[\"']xoxb-",
        r"SLACK_SIGNING_SECRET\s*=\s*[\"'][^\"']+[\"']",
        r"NEO4J_PASSWORD\s*=\s*[\"'][^\"']+[\"']",
        r"CONFLUENCE_API_TOKEN\s*=\s*[\"'][^\"']+[\"']",
        r"GEMINI_API_KEY\s*=\s*[\"'][^\"']+[\"']",
    ],

    # HIGH: PII in logs
    'pii_logging': [
        r'logger\.(info|debug)\s*\([^)]*user_id',
        r'logger\.(info|debug)\s*\([^)]*username',
        r'logger\.(info|debug)\s*\([^)]*channel_id',
        r'logger\.(info|debug)\s*\([^)]*reporter_name',
        r'logger\.(info|debug)\s*\([^)]*reporter_id',
        r'logger\.(info|debug)\s*\([^)]*slack_user',
        r'print\s*\([^)]*user_id',
    ],

    # HIGH: Security control bypass
    'security_bypass': [
        r'ADMIN_PASSWORD\s*=\s*["\']changeme["\']',
        r'verify_signature\s*=\s*False',
        r'SIGNING_SECRET_VERIFY\s*=\s*False',
    ],

    # MEDIUM: Injection risks
    'injection_risks': [
        r'eval\s*\(',                             # eval() usage
        r'exec\s*\(',                             # exec() usage
        r'subprocess.*shell\s*=\s*True',         # Shell injection risk
        r'os\.system\s*\(',                       # OS command execution
    ],

    # MEDIUM: Error message exposure
    'error_exposure': [
        r'except.*:\s*\n\s*return\s+str\(e\)',   # Raw exception to user
        r'raise\s+.*password',                    # Password in exception
        r'raise\s+.*api_key',                     # API key in exception
        r'HTTPException.*detail=.*password',    # Password in HTTP error
    ],

    # LOW: Potential issues to flag
    'potential_issues': [
        r'verify\s*=\s*False',                   # SSL verification disabled
        r'ssl\._create_unverified_context',      # Unverified SSL
        r'random\.',                             # Not cryptographically secure
        r'md5\s*\(',                             # Weak hash
        r'sha1\s*\(',                             # Weak hash (for passwords)
    ],
}

# File sensitivity classification based on filename patterns
# Used to prioritize review focus and add context to findings

FILE_SENSITIVITY = {
    # CRITICAL: Direct credential handling
    'config.py': 'CRITICAL',
    'settings.py': 'CRITICAL',
    '.env': 'CRITICAL',

    # HIGH: Core business logic with sensitive operations
    'database.py': 'HIGH',
    'bot.py': 'HIGH',
    'graphiti_builder.py': 'HIGH',
    'graphiti_indexer.py': 'HIGH',
    'graphiti_client.py': 'HIGH',
    'graphiti_retriever.py': 'HIGH',
    'client.py': 'HIGH',

    # MEDIUM: External service integrations and UI
    'downloader.py': 'MEDIUM',
    'hybrid.py': 'MEDIUM',
    'streamlit_app.py': 'MEDIUM',
}

# File patterns for sensitivity (when exact match not found)
FILE_SENSITIVITY_PATTERNS = [
    (r'.*config.*\.py$', 'CRITICAL'),
    (r'.*secret.*', 'CRITICAL'),
    (r'.*credential.*', 'CRITICAL'),
    (r'.*\.env.*', 'CRITICAL'),
    (r'.*\.tfvars.*', 'CRITICAL'),
    (r'.*auth.*\.py$', 'HIGH'),
    (r'.*graphiti.*\.py$', 'HIGH'),
    (r'.*neo4j.*\.py$', 'HIGH'),
    (r'.*slack.*\.py$', 'MEDIUM'),
    (r'.*confluence.*\.py$', 'MEDIUM'),
    (r'.*\.tf$', 'MEDIUM'),
    (r'.*test.*\.py$', 'LOW'),
    (r'.*_test\.py$', 'LOW'),
]

# OWASP Top 10 2021 categories for structured reporting
OWASP_CATEGORIES = {
    'A01': 'Broken Access Control',
    'A02': 'Cryptographic Failures',
    'A03': 'Injection',
    'A04': 'Insecure Design',
    'A05': 'Security Misconfiguration',
    'A06': 'Vulnerable Components',
    'A07': 'Identification and Authentication Failures',
    'A08': 'Software and Data Integrity Failures',
    'A09': 'Security Logging and Monitoring Failures',
    'A10': 'Server-Side Request Forgery',
}

# Mapping of pattern categories to OWASP categories
PATTERN_TO_OWASP = {
    'credential_logging': 'A09',      # Logging failures
    'hardcoded_credentials': 'A02',   # Cryptographic failures
    'pii_logging': 'A09',              # Logging failures
    'security_bypass': 'A05',         # Security misconfiguration
    'injection_risks': 'A03',         # Injection
    'error_exposure': 'A05',          # Security misconfiguration
    'potential_issues': 'A02',        # Cryptographic failures
}


def get_file_sensitivity(filename: str) -> str:
    """
    Determine the security sensitivity level of a file.

    Args:
        filename: The name or path of the file

    Returns:
        Sensitivity level: CRITICAL, HIGH, MEDIUM, or LOW
    """
    import os
    import re

    basename = os.path.basename(filename)

    # Check exact matches first
    if basename in FILE_SENSITIVITY:
        return FILE_SENSITIVITY[basename]

    # Check patterns
    for pattern, sensitivity in FILE_SENSITIVITY_PATTERNS:
        if re.match(pattern, filename, re.IGNORECASE):
            return sensitivity

    # Default to MEDIUM for Python files, LOW for others
    if filename.endswith('.py'):
        return 'MEDIUM'
    return 'LOW'


def get_severity_for_category(category: str) -> str:
    """
    Get the default severity level for a pattern category.

    Args:
        category: The pattern category name

    Returns:
        Severity level: CRITICAL, HIGH, MEDIUM, or LOW
    """
    severity_map = {
        'credential_logging': 'CRITICAL',
        'hardcoded_credentials': 'CRITICAL',
        'pii_logging': 'HIGH',
        'security_bypass': 'CRITICAL',
        'injection_risks': 'HIGH',
        'error_exposure': 'MEDIUM',
        'potential_issues': 'LOW',
    }
    return severity_map.get(category, 'MEDIUM')
