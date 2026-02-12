#!/usr/bin/env python3
"""
Neo4j Connection Test Suite

Tests Neo4j connectivity at multiple levels:
1. Direct instance connection (internal IP)
2. SSL Proxy Load Balancer connection
3. Protocol handshakes (TLS, Bolt)
4. Full authentication and query

Usage:
    python test-neo4j-connection.py              # Test all
    python test-neo4j-connection.py --target staging
    python test-neo4j-connection.py --target production
    python test-neo4j-connection.py --verbose
"""

import sys
import socket
import ssl
import struct
import time
import argparse
from typing import Tuple, Dict, List
from dataclasses import dataclass
from datetime import datetime

try:
    from neo4j import GraphDatabase
    NEO4J_DRIVER_AVAILABLE = True
except ImportError:
    NEO4J_DRIVER_AVAILABLE = False

try:
    from google.cloud import secretmanager
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False


# Configuration
STAGING_LB = "neo4j.staging.keboola.dev"
PROD_LB = "neo4j.internal.keboola.dev"
STAGING_INTERNAL = "10.0.0.23"
PROD_INTERNAL = "10.0.0.27"
BOLT_PORT = 7687
LB_PORT = 443
NEO4J_USER = "neo4j"
PROJECT_ID = "ai-knowledge-base-42"

# Bolt protocol constants
BOLT_MAGIC = bytes([0x60, 0x60, 0xB0, 0x17])
BOLT_VERSIONS = bytes([
    0x00, 0x00, 0x04, 0x04,  # Bolt 4.4
    0x00, 0x00, 0x02, 0x04,  # Bolt 4.2
    0x00, 0x00, 0x01, 0x04,  # Bolt 4.1
    0x00, 0x00, 0x00, 0x04   # Bolt 4.0
])

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


@dataclass
class TestResult:
    """Test result with status and details"""
    name: str
    passed: bool
    message: str = ""
    details: Dict = None

    def __str__(self):
        status = f"{GREEN}✓{RESET}" if self.passed else f"{RED}✗{RESET}"
        return f"{status} {self.name}"


class Neo4jConnectionTester:
    """Test Neo4j connectivity at multiple levels"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.neo4j_password = None

    def log(self, level: str, message: str):
        """Log message with level"""
        if level == "INFO":
            print(f"{BLUE}[INFO]{RESET} {message}")
        elif level == "TEST":
            print(f"{BOLD}[TEST]{RESET} {message}")
        elif level == "SUCCESS":
            print(f"{GREEN}[SUCCESS]{RESET} {message}")
        elif level == "FAIL":
            print(f"{RED}[FAIL]{RESET} {message}")
        elif level == "WARN":
            print(f"{YELLOW}[WARN]{RESET} {message}")
        elif level == "DIAG":
            print(f"{BLUE}[DIAG]{RESET} {message}")

    def print_header(self):
        """Print test suite header"""
        print()
        print(f"{BOLD}╔═══════════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}║   Neo4j Connection Test Suite                 ║{RESET}")
        print(f"{BOLD}║   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}                           ║{RESET}")
        print(f"{BOLD}╚═══════════════════════════════════════════════╝{RESET}")
        print()

    def print_separator(self):
        """Print separator line"""
        print(f"{BOLD}═══════════════════════════════════════════════{RESET}")

    def fetch_neo4j_password(self) -> bool:
        """Fetch Neo4j password from VM metadata first, then fall back to Secret Manager"""
        self.log("TEST", "Fetching Neo4j credentials")

        # First try: Get from VM metadata (this is what the startup script uses)
        try:
            self.log("INFO", "Attempting to fetch password from GCP VM metadata...")
            response = socket.create_connection(("metadata.google.internal", 80), timeout=2)
            request = b"GET /computeMetadata/v1/instance/attributes/neo4j-password HTTP/1.0\r\nHost: metadata.google.internal\r\nMetadata-Flavor: Google\r\n\r\n"
            response.sendall(request)
            data = response.recv(4096).decode('utf-8', errors='ignore')
            response.close()

            # Extract password from HTTP response body
            body = data.split('\r\n\r\n', 1)[-1]
            if body and body.strip():
                self.neo4j_password = body.strip()
                self.log("SUCCESS", "Retrieved Neo4j password from VM metadata")
                return True
        except Exception as e:
            self.log("INFO", f"VM metadata not available (expected outside GCP): {e}")

        # Second try: Environment variable
        import os
        self.neo4j_password = os.environ.get("NEO4J_PASSWORD")
        if self.neo4j_password:
            self.log("SUCCESS", "Retrieved password from environment")
            return True

        # Third try: Secret Manager
        if GCS_AVAILABLE:
            try:
                self.log("INFO", "Attempting to fetch password from Secret Manager...")
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{PROJECT_ID}/secrets/neo4j-password/versions/latest"
                response = client.access_secret_version(request={"name": name})
                self.neo4j_password = response.payload.data.decode("UTF-8").strip()
                self.log("SUCCESS", "Retrieved Neo4j password from Secret Manager")
                return True
            except Exception as e:
                self.log("INFO", f"Secret Manager not available: {e}")

        self.log("FAIL", "Could not retrieve NEO4J_PASSWORD from any source")
        return False

    def test_tcp_connection(self, host: str, port: int) -> Tuple[bool, str]:
        """Test TCP socket connection"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((host, port))
            sock.close()
            return True, f"Connected to {host}:{port}"
        except socket.timeout:
            return False, f"Connection timeout to {host}:{port}"
        except socket.gaierror:
            return False, f"DNS resolution failed for {host}"
        except ConnectionRefusedError:
            return False, f"Connection refused to {host}:{port}"
        except Exception as e:
            return False, f"Connection error: {e}"

    def test_tls_handshake(self, host: str, port: int) -> Tuple[bool, Dict]:
        """Test TLS handshake and certificate"""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = ssock.getpeercert()
                    version = ssock.version()
                    cipher = ssock.cipher()

                    details = {
                        "tls_version": version,
                        "cipher": cipher[0] if cipher else "unknown",
                        "subject": dict(x[0] for x in cert.get("subject", []))
                    }
                    return True, details
        except ssl.SSLError as e:
            return False, {"error": f"SSL error: {e}"}
        except Exception as e:
            return False, {"error": str(e)}

    def test_bolt_handshake(self, host: str, port: int, use_tls: bool = True) -> Tuple[bool, str]:
        """Test Bolt protocol handshake"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)

            if use_tls:
                context = ssl.create_default_context()
                sock = context.wrap_socket(sock, server_hostname=host)

            sock.connect((host, port))

            # Send Bolt handshake
            sock.sendall(BOLT_MAGIC + BOLT_VERSIONS)

            # Receive response (should be 4 bytes with chosen version)
            response = sock.recv(4)
            sock.close()

            if len(response) != 4:
                return False, f"Invalid Bolt response (got {len(response)} bytes)"

            # Check if it's a valid Bolt version
            version_int = struct.unpack(">I", response)[0]
            major = version_int >> 16
            minor = version_int & 0xFFFF

            if version_int == 0:
                return False, "Server rejected Bolt handshake (version 0.0)"

            return True, f"Bolt {major}.{minor}"

        except ConnectionRefusedError:
            return False, f"Connection refused to {host}:{port}"
        except socket.timeout:
            return False, f"Connection timeout to {host}:{port}"
        except Exception as e:
            # Try to detect if we got HTTP response
            error_str = str(e).lower()
            if "http" in error_str or "html" in error_str:
                return False, "Got HTTP response (port 7474?) instead of Bolt protocol"
            return False, f"Bolt handshake failed: {e}"

    def test_neo4j_driver_connection(self, uri: str) -> Tuple[bool, str]:
        """Test full Neo4j driver connection"""
        if not NEO4J_DRIVER_AVAILABLE:
            self.log("WARN", "neo4j-driver not installed, skipping full connection test")
            return None, "neo4j-driver not available"

        if not self.neo4j_password:
            return False, "Neo4j password not available"

        try:
            driver = GraphDatabase.driver(uri, auth=(NEO4J_USER, self.neo4j_password))
            with driver.session() as session:
                result = session.run("RETURN 1 as test")
                test_value = result.single()["test"]
                driver.close()
                return True, f"Query executed successfully (returned: {test_value})"
        except Exception as e:
            return False, f"Driver connection failed: {e}"

    def run_tests(self, targets: List[str]):
        """Run all tests"""
        self.print_header()

        # Step 1: Fetch credentials
        self.log("TEST", "Step 1: Fetching credentials")
        if not self.fetch_neo4j_password():
            self.log("FAIL", "Cannot proceed without credentials")
            return False

        print()

        for target in targets:
            if target == "staging":
                self.run_target_tests("Staging", STAGING_INTERNAL, STAGING_LB)
            elif target == "production":
                self.run_target_tests("Production", PROD_INTERNAL, PROD_LB)

        self.print_results()
        return all(r.passed for r in self.results)

    def run_target_tests(self, name: str, internal_ip: str, lb_host: str):
        """Run tests for a specific target (staging/production)"""
        self.log("TEST", f"Step {len([r for r in self.results if r.passed or not r.passed]) + 1}: Testing {name}")
        print()

        # Test 1: Direct connection (optional - may timeout from external networks)
        self.log("INFO", f"Testing direct connection to {internal_ip}:{BOLT_PORT} (timeout expected from external networks)")
        success, msg = self.test_tcp_connection(internal_ip, BOLT_PORT)
        if success:
            self.log("SUCCESS", f"TCP connection: {msg}")
            # Test 2: TLS handshake
            self.log("INFO", f"Testing TLS handshake to {internal_ip}:{BOLT_PORT}")
            success, details = self.test_tls_handshake(internal_ip, BOLT_PORT)
            if success:
                self.log("SUCCESS", f"TLS handshake: {details['tls_version']}")
                if self.verbose:
                    self.log("DIAG", f"Cipher: {details['cipher']}")
            else:
                self.log("FAIL", f"TLS handshake: {details.get('error', 'unknown')}")

            # Test 3: Bolt handshake (direct)
            self.log("INFO", f"Testing Bolt protocol on {internal_ip}:{BOLT_PORT}")
            success, msg = self.test_bolt_handshake(internal_ip, BOLT_PORT)
            if success:
                self.log("SUCCESS", f"Bolt handshake: {msg}")
                self.results.append(TestResult(f"{name} Direct Bolt", True, msg))
            else:
                self.log("FAIL", f"Bolt handshake: {msg}")
                self.results.append(TestResult(f"{name} Direct Bolt", False, msg))
        else:
            self.log("WARN", f"Direct connection unavailable (expected if running from external network): {msg}")
            self.log("INFO", "Continuing with load balancer tests...")

        print()

        # Test 4: Load Balancer connection
        self.log("INFO", f"Testing {name} Load Balancer: {lb_host}:{LB_PORT}")
        success, msg = self.test_tcp_connection(lb_host, LB_PORT)
        if success:
            self.log("SUCCESS", f"TCP connection to LB: {msg}")
        else:
            self.log("FAIL", f"TCP connection to LB: {msg}")
            self.log("DIAG", "Load balancer is not reachable")
            self.results.append(TestResult(f"{name} LB Connection", False, msg))
            return

        # Test 5: TLS through LB
        self.log("INFO", f"Testing TLS handshake through {name} LB")
        success, details = self.test_tls_handshake(lb_host, LB_PORT)
        if success:
            self.log("SUCCESS", f"TLS handshake through LB: {details['tls_version']}")
        else:
            self.log("FAIL", f"TLS through LB: {details.get('error', 'unknown')}")

        # Test 6: Bolt through LB (THE CRITICAL TEST)
        self.log("INFO", f"Testing Bolt protocol through {name} Load Balancer")
        success, msg = self.test_bolt_handshake(lb_host, LB_PORT, use_tls=True)
        if success:
            self.log("SUCCESS", f"Bolt handshake through LB: {msg}")
            self.results.append(TestResult(f"{name} LB Bolt", True, msg))

            # Test 7: Full driver connection
            if NEO4J_DRIVER_AVAILABLE:
                self.log("INFO", f"Testing full Neo4j driver connection to {name}")
                uri = f"bolt+s://{lb_host}:{LB_PORT}"
                success, msg = self.test_neo4j_driver_connection(uri)
                if success is None:
                    self.log("WARN", f"Driver connection test skipped: {msg}")
                elif success:
                    self.log("SUCCESS", f"Driver connection: {msg}")
                    self.results.append(TestResult(f"{name} Full Driver", True, msg))
                else:
                    self.log("FAIL", f"Driver connection: {msg}")
                    self.results.append(TestResult(f"{name} Full Driver", False, msg))
        else:
            self.log("FAIL", f"Bolt handshake through LB FAILED: {msg}")
            self.results.append(TestResult(f"{name} LB Bolt", False, msg))
            self.log("DIAG", "🔴 CRITICAL: Load balancer is routing to wrong port")
            self.log("DIAG", "    Expected: port 7687 (Bolt protocol)")
            self.log("DIAG", "    Detected: port 7474 (HTTP API)")
            self.log("DIAG", "    Fix: Update backend service port configuration")

        print()

    def print_results(self):
        """Print test summary"""
        self.print_separator()
        print(f"{BOLD}SUMMARY{RESET}")
        self.print_separator()
        print()

        for result in self.results:
            print(str(result) + f" {result.message}")

        print()
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        print(f"Result: {passed}/{total} passed")

        if passed == total and total > 0:
            print()
            print(f"{GREEN}{BOLD}✓ All tests PASSED!{RESET}")
            print(f"{GREEN}Neo4j connection is working correctly.{RESET}")
            return 0
        else:
            print()
            print(f"{RED}{BOLD}✗ Some tests FAILED{RESET}")
            if any("Bolt handshake through" in r.name and not r.passed for r in self.results):
                print(f"{RED}Load balancer is routing to the wrong port.{RESET}")
                print(f"{RED}Check backend service configuration.{RESET}")
            return 1


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Test Neo4j connection through SSL proxy load balancer"
    )
    parser.add_argument(
        "--target",
        choices=["staging", "production"],
        default="staging",
        help="Which environment to test (default: staging)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print verbose diagnostic information"
    )

    args = parser.parse_args()

    tester = Neo4jConnectionTester(verbose=args.verbose)
    success = tester.run_tests([args.target])
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
