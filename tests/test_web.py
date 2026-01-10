"""Tests for the Streamlit web UI module."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


# =============================================================================
# Test Helper Functions
# =============================================================================


class TestAuthFunction:
    """Tests for the authentication function."""

    def test_check_auth_valid(self):
        """Test valid credentials."""
        with patch("knowledge_base.web.streamlit_app.settings") as mock_settings:
            mock_settings.ADMIN_USERNAME = "admin"
            mock_settings.ADMIN_PASSWORD = "secret123"

            from knowledge_base.web.streamlit_app import check_auth

            assert check_auth("admin", "secret123") is True

    def test_check_auth_invalid_username(self):
        """Test invalid username."""
        with patch("knowledge_base.web.streamlit_app.settings") as mock_settings:
            mock_settings.ADMIN_USERNAME = "admin"
            mock_settings.ADMIN_PASSWORD = "secret123"

            from knowledge_base.web.streamlit_app import check_auth

            assert check_auth("wrong", "secret123") is False

    def test_check_auth_invalid_password(self):
        """Test invalid password."""
        with patch("knowledge_base.web.streamlit_app.settings") as mock_settings:
            mock_settings.ADMIN_USERNAME = "admin"
            mock_settings.ADMIN_PASSWORD = "secret123"

            from knowledge_base.web.streamlit_app import check_auth

            assert check_auth("admin", "wrong") is False


class TestGetDbSize:
    """Tests for the get_db_size function."""

    def test_db_size_file_exists(self):
        """Test database size calculation when file exists."""
        from knowledge_base.web.streamlit_app import get_db_size

        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                # Test bytes
                mock_stat.return_value.st_size = 500
                assert get_db_size() == "500 B"

                # Test kilobytes
                mock_stat.return_value.st_size = 2048
                assert get_db_size() == "2.0 KB"

                # Test megabytes
                mock_stat.return_value.st_size = 2 * 1024 * 1024
                assert get_db_size() == "2.0 MB"

    def test_db_size_file_not_exists(self):
        """Test database size when file doesn't exist."""
        from knowledge_base.web.streamlit_app import get_db_size

        with patch.object(Path, "exists", return_value=False):
            assert get_db_size() == "N/A"


class TestGetAdminStats:
    """Tests for the get_admin_stats function."""

    @patch("knowledge_base.web.streamlit_app.get_session")
    @patch("knowledge_base.web.streamlit_app.get_db_size")
    def test_get_admin_stats_empty_db(self, mock_db_size, mock_get_session):
        """Test admin stats with empty database."""
        mock_db_size.return_value = "0 B"

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = 0
        mock_get_session.return_value = mock_session

        from knowledge_base.web.streamlit_app import get_admin_stats

        stats = get_admin_stats()

        assert stats["total_pages"] == 0
        assert stats["total_chunks"] == 0
        assert stats["database_size"] == "0 B"
        mock_session.close.assert_called_once()

    @patch("knowledge_base.web.streamlit_app.get_session")
    @patch("knowledge_base.web.streamlit_app.get_db_size")
    def test_get_admin_stats_with_data(self, mock_db_size, mock_get_session):
        """Test admin stats with data."""
        mock_db_size.return_value = "1.5 MB"

        mock_session = MagicMock()
        # Configure return values for different queries
        mock_session.execute.return_value.scalar.side_effect = [
            100,  # total_pages
            90,   # active_pages
            500,  # total_chunks
            10,   # total_documents
            8,    # published_documents
            2,    # draft_documents
            3,    # open_issues
            2,    # documentation_gaps
            None, # last_sync
        ]
        mock_get_session.return_value = mock_session

        from knowledge_base.web.streamlit_app import get_admin_stats

        stats = get_admin_stats()

        assert stats["total_pages"] == 100
        assert stats["active_pages"] == 90
        assert stats["total_chunks"] == 500
        assert stats["database_size"] == "1.5 MB"


class TestGetGovernanceData:
    """Tests for the get_governance_data function."""

    @patch("knowledge_base.web.streamlit_app.get_session")
    def test_get_governance_data_empty(self, mock_get_session):
        """Test governance data with empty database."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_session.execute.return_value.all.return_value = []
        mock_get_session.return_value = mock_session

        from knowledge_base.web.streamlit_app import get_governance_data

        data = get_governance_data()

        assert data["recent_issues"] == []
        assert data["gaps"] == []
        assert data["stale_pages"] == []
        assert data["space_stats"] == []
        mock_session.close.assert_called_once()


class TestSearchApi:
    """Tests for the search_api function."""

    @patch("knowledge_base.web.streamlit_app.requests.post")
    def test_search_api_success(self, mock_post):
        """Test successful API call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [{"title": "Test", "score": 0.9}],
            "answer": "Test answer",
        }
        mock_post.return_value = mock_response

        from knowledge_base.web.streamlit_app import search_api

        result = search_api("test query")

        assert "results" in result
        assert result["results"][0]["title"] == "Test"
        mock_post.assert_called_once()

    @patch("knowledge_base.web.streamlit_app.requests.post")
    def test_search_api_error(self, mock_post):
        """Test API error handling."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        from knowledge_base.web.streamlit_app import search_api

        result = search_api("test query")

        assert "error" in result
        assert "500" in result["error"]

    @patch("knowledge_base.web.streamlit_app.requests.post")
    def test_search_api_connection_error(self, mock_post):
        """Test connection error handling."""
        import requests
        mock_post.side_effect = requests.exceptions.ConnectionError()

        from knowledge_base.web.streamlit_app import search_api

        result = search_api("test query")

        assert "error" in result
        assert "Cannot connect" in result["error"]


# =============================================================================
# Config Tests
# =============================================================================


class TestConfig:
    """Tests for configuration."""

    def test_admin_credentials_in_settings(self):
        """Test that admin credentials are in settings."""
        from knowledge_base.config import settings

        assert hasattr(settings, "ADMIN_USERNAME")
        assert hasattr(settings, "ADMIN_PASSWORD")

    def test_default_admin_username(self):
        """Test default admin username."""
        from knowledge_base.config import settings

        assert settings.ADMIN_USERNAME == "admin"


# =============================================================================
# Integration Tests (without running Streamlit)
# =============================================================================


class TestModuleImport:
    """Tests that the module imports correctly."""

    def test_import_streamlit_app(self):
        """Test that streamlit_app module can be imported."""
        try:
            from knowledge_base.web import streamlit_app
            assert streamlit_app is not None
        except ImportError as e:
            pytest.fail(f"Failed to import streamlit_app: {e}")

    def test_import_functions(self):
        """Test that key functions can be imported."""
        from knowledge_base.web.streamlit_app import (
            check_auth,
            get_db_size,
            get_admin_stats,
            get_governance_data,
            search_api,
        )

        assert callable(check_auth)
        assert callable(get_db_size)
        assert callable(get_admin_stats)
        assert callable(get_governance_data)
        assert callable(search_api)


# =============================================================================
# FastAPI Root Endpoint Test
# =============================================================================


class TestFastAPIRoot:
    """Tests for the FastAPI root endpoint."""

    def test_root_returns_info(self):
        """Test that root endpoint returns app info."""
        from fastapi.testclient import TestClient
        from knowledge_base.main import app

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "streamlit_ui" in data
