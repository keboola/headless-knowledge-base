"""Streamlit Web UI for the Knowledge Base."""

import asyncio
import json
import requests
from datetime import datetime
from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from knowledge_base.config import settings
from knowledge_base.db.models import (
    AreaApprover,
    Chunk,
    Document,
    DocumentationGap,
    DocumentVersion,
    GovernanceIssue,
    RawPage,
)
from knowledge_base.documents.models import (
    ApprovalDecision,
    DocumentArea,
    DocumentStatus,
    DocumentType,
    Classification,
)

# Page config
st.set_page_config(
    page_title="Knowledge Base",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Database connection (sync)
sync_db_url = settings.DATABASE_URL.replace("+aiosqlite", "")
engine = create_engine(sync_db_url)
SessionLocal = sessionmaker(bind=engine)


def get_session():
    """Get a database session."""
    return SessionLocal()


def check_auth(username: str, password: str) -> bool:
    """Verify admin credentials."""
    return (
        username == settings.ADMIN_USERNAME
        and password == settings.ADMIN_PASSWORD
    )


def get_db_size() -> str:
    """Get the database file size."""
    db_path = Path("knowledge_base.db")
    if db_path.exists():
        size = db_path.stat().st_size
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        else:
            return f"{size / (1024 * 1024):.1f} MB"
    return "N/A"


def get_admin_stats() -> dict:
    """Get statistics for the admin dashboard."""
    session = get_session()
    try:
        total_pages = session.execute(select(func.count(RawPage.id))).scalar() or 0
        active_pages = (
            session.execute(
                select(func.count(RawPage.id)).where(RawPage.status == "active")
            ).scalar()
            or 0
        )
        total_chunks = session.execute(select(func.count(Chunk.id))).scalar() or 0
        total_docs = session.execute(select(func.count(Document.id))).scalar() or 0
        published_docs = (
            session.execute(
                select(func.count(Document.id)).where(Document.status == "published")
            ).scalar()
            or 0
        )
        draft_docs = (
            session.execute(
                select(func.count(Document.id)).where(Document.status == "draft")
            ).scalar()
            or 0
        )
        open_issues = (
            session.execute(
                select(func.count(GovernanceIssue.id)).where(
                    GovernanceIssue.status == "open"
                )
            ).scalar()
            or 0
        )
        gap_count = (
            session.execute(
                select(func.count(DocumentationGap.id)).where(
                    DocumentationGap.status == "open"
                )
            ).scalar()
            or 0
        )
        last_sync = session.execute(
            select(RawPage.downloaded_at).order_by(RawPage.downloaded_at.desc()).limit(1)
        ).scalar()

        return {
            "total_pages": total_pages,
            "active_pages": active_pages,
            "total_chunks": total_chunks,
            "total_documents": total_docs,
            "published_documents": published_docs,
            "draft_documents": draft_docs,
            "open_issues": open_issues,
            "documentation_gaps": gap_count,
            "last_sync": last_sync.isoformat() if last_sync else "Never",
            "database_size": get_db_size(),
        }
    finally:
        session.close()


def get_governance_data() -> dict:
    """Get data for the governance dashboard."""
    session = get_session()
    try:
        recent_issues = session.execute(
            select(GovernanceIssue)
            .where(GovernanceIssue.status == "open")
            .order_by(GovernanceIssue.detected_at.desc())
            .limit(10)
        ).scalars().all()

        gaps = session.execute(
            select(DocumentationGap)
            .where(DocumentationGap.status == "open")
            .order_by(DocumentationGap.query_count.desc())
            .limit(10)
        ).scalars().all()

        stale_pages = session.execute(
            select(RawPage)
            .where(RawPage.is_potentially_stale == True)  # noqa: E712
            .order_by(RawPage.updated_at.asc())
            .limit(10)
        ).scalars().all()

        space_stats = session.execute(
            select(RawPage.space_key, func.count(RawPage.id).label("count"))
            .group_by(RawPage.space_key)
        ).all()

        return {
            "recent_issues": recent_issues,
            "gaps": gaps,
            "stale_pages": stale_pages,
            "space_stats": space_stats,
        }
    finally:
        session.close()


def search_api(query: str, top_k: int = 5) -> dict:
    """Call the search API."""
    try:
        response = requests.post(
            "http://localhost:8000/api/v1/search",
            json={"query": query, "top_k": top_k},
            timeout=30,
        )
        if response.status_code == 200:
            return response.json()
        else:
            return {"error": f"API returned status {response.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to API. Is the server running?"}
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# Document Management Functions
# =============================================================================


def get_documents(
    status: str | None = None,
    area: str | None = None,
    doc_type: str | None = None,
    limit: int = 50,
) -> list[Document]:
    """Get documents with optional filtering."""
    session = get_session()
    try:
        stmt = select(Document)
        if status and status != "All":
            stmt = stmt.where(Document.status == status)
        if area and area != "All":
            stmt = stmt.where(Document.area == area)
        if doc_type and doc_type != "All":
            stmt = stmt.where(Document.doc_type == doc_type)
        stmt = stmt.order_by(Document.created_at.desc()).limit(limit)
        result = session.execute(stmt)
        return list(result.scalars().all())
    finally:
        session.close()


def get_document_by_id(doc_id: str) -> Document | None:
    """Get a document by ID."""
    session = get_session()
    try:
        stmt = select(Document).where(Document.doc_id == doc_id)
        result = session.execute(stmt)
        return result.scalars().first()
    finally:
        session.close()


def get_pending_approvals(approver_id: str) -> list[Document]:
    """Get documents pending approval by a specific user."""
    session = get_session()
    try:
        stmt = select(Document).where(Document.status == DocumentStatus.IN_REVIEW.value)
        result = session.execute(stmt)
        documents = result.scalars().all()

        pending = []
        for doc in documents:
            pending_approvers = json.loads(doc.pending_approvers) if doc.pending_approvers else []
            if approver_id in pending_approvers:
                pending.append(doc)
        return pending
    finally:
        session.close()


def get_document_creator():
    """Get a DocumentCreator instance."""
    from knowledge_base.documents.creator import DocumentCreator
    from knowledge_base.documents.approval import ApprovalConfig

    session = get_session()
    config = ApprovalConfig(require_all_approvers=False)

    # Try to get LLM
    llm = None
    try:
        from knowledge_base.rag.factory import get_llm as get_llm_async
        llm = asyncio.run(get_llm_async())
    except Exception:
        pass

    return DocumentCreator(session=session, llm=llm, approval_config=config)


def status_badge(status: str) -> str:
    """Return status with color indicator."""
    colors = {
        "draft": "🔵",
        "in_review": "🟡",
        "approved": "🟢",
        "published": "✅",
        "rejected": "🔴",
        "archived": "⚪",
    }
    return f"{colors.get(status, '⚫')} {status.upper()}"


def safe_async_call(coro, error_message: str = "Operation failed"):
    """Safely execute an async coroutine."""
    try:
        return asyncio.run(coro)
    except Exception as e:
        st.error(f"{error_message}: {e}")
        return None


# =============================================================================
# Sidebar Navigation
# =============================================================================

st.sidebar.title("📚 Knowledge Base")
page = st.sidebar.radio(
    "Navigation",
    ["🔍 Search", "📄 Documents", "📊 Admin Dashboard", "📋 Governance"],
    label_visibility="collapsed",
)

# Admin authentication state
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False


# =============================================================================
# Search Page
# =============================================================================

if page == "🔍 Search":
    st.title("🔍 Knowledge Base Search")
    st.markdown("Ask questions about your documentation")

    query = st.text_input(
        "Search query",
        placeholder="What would you like to know?",
        label_visibility="collapsed",
    )

    col1, col2 = st.columns([4, 1])
    with col1:
        search_clicked = st.button("Search", type="primary", use_container_width=True)
    with col2:
        top_k = st.selectbox("Results", [5, 10, 20], index=0, label_visibility="collapsed")

    if search_clicked and query:
        with st.spinner("Searching..."):
            results = search_api(query, top_k)

        if "error" in results:
            st.error(results["error"])
        else:
            # Show answer if available
            if results.get("answer"):
                st.markdown("### Answer")
                st.markdown(results["answer"])
                st.divider()

            # Show search results
            if results.get("results"):
                st.markdown("### Sources")
                for i, result in enumerate(results["results"], 1):
                    score = result.get("score", 0) * 100
                    with st.expander(
                        f"**{result.get('title', 'Untitled')}** ({score:.0f}% match)",
                        expanded=(i <= 2),
                    ):
                        st.markdown(result.get("content", "")[:500] + "...")
                        cols = st.columns(3)
                        if result.get("space_key"):
                            cols[0].caption(f"📁 {result['space_key']}")
                        if result.get("url"):
                            cols[1].markdown(f"[View Source]({result['url']})")
            else:
                st.info("No results found.")


# =============================================================================
# Documents Page
# =============================================================================

elif page == "📄 Documents":
    st.title("📄 Document Management")

    # Authentication required
    if not st.session_state.authenticated:
        st.warning("Please log in to manage documents.")
        with st.form("login_form_docs"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

            if submitted:
                if check_auth(username, password):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    else:
        # Logout button
        if st.sidebar.button("Logout", key="logout_docs"):
            st.session_state.authenticated = False
            st.rerun()

        # Initialize session state for document management
        if "doc_view" not in st.session_state:
            st.session_state.doc_view = "list"
        if "selected_doc_id" not in st.session_state:
            st.session_state.selected_doc_id = None
        if "edit_mode" not in st.session_state:
            st.session_state.edit_mode = False

        # Sub-navigation tabs
        doc_tab = st.radio(
            "View",
            ["Browse Documents", "Create New", "Pending Approvals"],
            horizontal=True,
            label_visibility="collapsed",
        )

        st.divider()

        # =====================================================================
        # Browse Documents View
        # =====================================================================
        if doc_tab == "Browse Documents":
            # Filters
            with st.expander("Filters", expanded=False):
                col1, col2, col3 = st.columns(3)
                with col1:
                    status_filter = st.selectbox(
                        "Status",
                        ["All"] + [s.value for s in DocumentStatus],
                    )
                with col2:
                    area_filter = st.selectbox(
                        "Area",
                        ["All"] + [a.value for a in DocumentArea],
                    )
                with col3:
                    type_filter = st.selectbox(
                        "Type",
                        ["All"] + [t.value for t in DocumentType],
                    )

            # Get documents
            documents = get_documents(
                status=status_filter if status_filter != "All" else None,
                area=area_filter if area_filter != "All" else None,
                doc_type=type_filter if type_filter != "All" else None,
            )

            if not documents:
                st.info("No documents found. Create one using the 'Create New' tab.")
            else:
                st.caption(f"Showing {len(documents)} document(s)")

                for doc in documents:
                    with st.container():
                        col1, col2, col3 = st.columns([4, 2, 1])

                        with col1:
                            st.markdown(f"**{doc.title}**")
                            st.caption(f"{doc.area} | {doc.doc_type}")

                        with col2:
                            st.markdown(status_badge(doc.status))

                        with col3:
                            if st.button("View", key=f"view_{doc.doc_id}"):
                                st.session_state.selected_doc_id = doc.doc_id
                                st.session_state.doc_view = "detail"
                                st.rerun()

                        st.divider()

            # Document Detail View (shown when a document is selected)
            if st.session_state.selected_doc_id:
                doc = get_document_by_id(st.session_state.selected_doc_id)

                if doc:
                    st.subheader(f"Document: {doc.title}")

                    # Back button
                    if st.button("← Back to List"):
                        st.session_state.selected_doc_id = None
                        st.session_state.edit_mode = False
                        st.rerun()

                    # Status and metadata
                    col1, col2, col3, col4 = st.columns(4)
                    col1.markdown(f"**Status:** {status_badge(doc.status)}")
                    col2.markdown(f"**Area:** {doc.area}")
                    col3.markdown(f"**Type:** {doc.doc_type}")
                    col4.markdown(f"**Version:** {doc.version or 1}")

                    st.caption(f"Created: {doc.created_at} by {doc.created_by}")
                    if doc.updated_at:
                        st.caption(f"Updated: {doc.updated_at} by {doc.updated_by}")

                    st.divider()

                    # Show rejection reason if rejected
                    if doc.status == DocumentStatus.REJECTED.value and doc.rejection_reason:
                        st.error(f"**Rejection Reason:** {doc.rejection_reason}")

                    # Content (editable or view mode)
                    if st.session_state.edit_mode:
                        edited_title = st.text_input("Title", value=doc.title)
                        edited_content = st.text_area(
                            "Content",
                            value=doc.content,
                            height=400,
                        )

                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("Save Changes", type="primary"):
                                creator = get_document_creator()
                                result = safe_async_call(
                                    creator.update_document(
                                        doc_id=doc.doc_id,
                                        content=edited_content,
                                        updated_by="admin",
                                        title=edited_title if edited_title != doc.title else None,
                                    ),
                                    "Failed to update document",
                                )
                                if result:
                                    st.success("Document updated!")
                                    st.session_state.edit_mode = False
                                    st.rerun()

                        with col2:
                            if st.button("Cancel"):
                                st.session_state.edit_mode = False
                                st.rerun()
                    else:
                        st.markdown(doc.content)

                    st.divider()

                    # Actions based on status
                    st.subheader("Actions")
                    col1, col2, col3, col4 = st.columns(4)

                    if doc.status == DocumentStatus.DRAFT.value:
                        with col1:
                            if st.button("Edit", use_container_width=True):
                                st.session_state.edit_mode = True
                                st.rerun()
                        with col2:
                            if st.button("Submit for Approval", type="primary", use_container_width=True):
                                creator = get_document_creator()
                                result = safe_async_call(
                                    creator.submit_for_approval(doc.doc_id, "admin"),
                                    "Failed to submit for approval",
                                )
                                if result:
                                    st.success("Submitted for approval!")
                                    st.rerun()

                    elif doc.status == DocumentStatus.REJECTED.value:
                        with col1:
                            if st.button("Edit & Resubmit", use_container_width=True):
                                st.session_state.edit_mode = True
                                st.rerun()

                    elif doc.status == DocumentStatus.APPROVED.value:
                        with col1:
                            if st.button("Publish", type="primary", use_container_width=True):
                                creator = get_document_creator()
                                result = safe_async_call(
                                    creator.publish_document(doc.doc_id),
                                    "Failed to publish document",
                                )
                                if result:
                                    st.success("Document published!")
                                    st.rerun()

                    elif doc.status == DocumentStatus.PUBLISHED.value:
                        with col1:
                            if st.button("Edit (creates new draft)", use_container_width=True):
                                st.session_state.edit_mode = True
                                st.rerun()
                        with col2:
                            archive_reason = st.text_input("Archive reason", key="archive_reason")
                        with col3:
                            if st.button("Archive", use_container_width=True):
                                if archive_reason:
                                    creator = get_document_creator()
                                    result = safe_async_call(
                                        creator.archive_document(doc.doc_id, "admin", archive_reason),
                                        "Failed to archive document",
                                    )
                                    if result:
                                        st.success("Document archived!")
                                        st.rerun()
                                else:
                                    st.warning("Please provide an archive reason")

        # =====================================================================
        # Create New Document View
        # =====================================================================
        elif doc_tab == "Create New":
            st.subheader("Create New Document")

            # Creation mode
            creation_mode = st.radio(
                "Creation Mode",
                ["Manual", "AI-Assisted"],
                horizontal=True,
                help="Manual: Write content yourself. AI-Assisted: Describe what you need and AI will draft it.",
            )

            # Common fields
            col1, col2 = st.columns(2)
            with col1:
                title = st.text_input("Title*", placeholder="Document title")
                area = st.selectbox(
                    "Area*",
                    options=[a.value for a in DocumentArea],
                )
            with col2:
                doc_type = st.selectbox(
                    "Document Type*",
                    options=[t.value for t in DocumentType],
                )
                classification = st.selectbox(
                    "Classification",
                    options=[c.value for c in Classification],
                    index=1,  # Default to "internal"
                )

            # Show approval notice for policies/procedures
            if doc_type in [DocumentType.POLICY.value, DocumentType.PROCEDURE.value]:
                st.info(f"{doc_type.title()} documents require approval before publishing.")
            else:
                st.success(f"{doc_type.title()} documents will be auto-published.")

            # Mode-specific fields
            if creation_mode == "Manual":
                content = st.text_area(
                    "Content*",
                    height=400,
                    placeholder="Write your document content here...",
                )

                if st.button("Create Document", type="primary", disabled=not (title and content)):
                    creator = get_document_creator()
                    result = safe_async_call(
                        creator.create_manual(
                            title=title,
                            content=content,
                            area=area,
                            doc_type=doc_type,
                            created_by="admin",
                            classification=classification,
                        ),
                        "Failed to create document",
                    )
                    if result:
                        st.success(f"Document created! Status: {result.status}")
                        st.session_state.selected_doc_id = result.doc_id
                        st.rerun()

            else:  # AI-Assisted
                description = st.text_area(
                    "Description*",
                    height=200,
                    placeholder="Describe what this document should cover. Be specific about the purpose, audience, and key points to include...",
                )

                st.info("AI will generate a draft based on your description. You can edit it before saving.")

                if st.button("Generate Draft", type="primary", disabled=not (title and description)):
                    creator = get_document_creator()
                    if not creator.drafter:
                        st.error("LLM not configured. Please use manual creation mode.")
                    else:
                        with st.spinner("Generating draft..."):
                            result = safe_async_call(
                                creator.create_from_description(
                                    title=title,
                                    description=description,
                                    area=area,
                                    doc_type=doc_type,
                                    created_by="admin",
                                    classification=classification,
                                ),
                                "Failed to generate draft",
                            )

                        if result:
                            doc, draft_result = result
                            st.success(f"Draft generated! Confidence: {draft_result.confidence * 100:.0f}%")

                            if draft_result.suggestions:
                                with st.expander("AI Suggestions", expanded=True):
                                    for suggestion in draft_result.suggestions:
                                        st.markdown(f"- {suggestion}")

                            st.markdown("### Generated Content")
                            st.markdown(doc.content)

                            st.session_state.selected_doc_id = doc.doc_id

        # =====================================================================
        # Pending Approvals View
        # =====================================================================
        elif doc_tab == "Pending Approvals":
            st.subheader("Pending Approvals")
            st.caption("Documents awaiting your approval")

            # Get all documents in review
            session = get_session()
            try:
                stmt = select(Document).where(Document.status == DocumentStatus.IN_REVIEW.value)
                result = session.execute(stmt)
                pending_docs = list(result.scalars().all())
            finally:
                session.close()

            if not pending_docs:
                st.success("No documents pending approval!")
            else:
                st.info(f"You have {len(pending_docs)} document(s) awaiting approval.")

                for doc in pending_docs:
                    with st.expander(f"**{doc.title}** ({doc.area} | {doc.doc_type})"):
                        st.caption(f"Submitted by: {doc.created_by}")

                        # Content preview
                        preview = doc.content[:500] + "..." if len(doc.content) > 500 else doc.content
                        st.markdown(preview)

                        st.divider()

                        # Approval actions
                        col1, col2, col3 = st.columns([2, 3, 2])

                        with col1:
                            if st.button("Approve", key=f"approve_{doc.doc_id}", type="primary"):
                                creator = get_document_creator()
                                decision = ApprovalDecision(
                                    doc_id=doc.doc_id,
                                    approved=True,
                                    approver_id="admin",
                                )
                                result = safe_async_call(
                                    creator.approval.process_decision(decision),
                                    "Failed to approve document",
                                )
                                if result:
                                    st.success("Document approved!")
                                    st.rerun()

                        with col2:
                            rejection_reason = st.text_input(
                                "Rejection reason",
                                key=f"reject_reason_{doc.doc_id}",
                                placeholder="Enter reason for rejection...",
                            )

                        with col3:
                            if st.button("Reject", key=f"reject_{doc.doc_id}"):
                                if rejection_reason:
                                    creator = get_document_creator()
                                    decision = ApprovalDecision(
                                        doc_id=doc.doc_id,
                                        approved=False,
                                        approver_id="admin",
                                        rejection_reason=rejection_reason,
                                    )
                                    result = safe_async_call(
                                        creator.approval.process_decision(decision),
                                        "Failed to reject document",
                                    )
                                    if result:
                                        st.warning("Document rejected.")
                                        st.rerun()
                                else:
                                    st.error("Please provide a rejection reason")


# =============================================================================
# Admin Dashboard
# =============================================================================

elif page == "📊 Admin Dashboard":
    st.title("📊 Admin Dashboard")

    # Authentication
    if not st.session_state.authenticated:
        st.warning("Please log in to access the admin dashboard.")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

            if submitted:
                if check_auth(username, password):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    else:
        # Logout button
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.rerun()

        # Stats
        stats = get_admin_stats()

        # Metrics row 1
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Pages", stats["total_pages"], f"{stats['active_pages']} active")
        col2.metric("Indexed Chunks", stats["total_chunks"])
        col3.metric("Documents", stats["total_documents"])
        col4.metric("Database Size", stats["database_size"])

        # Metrics row 2
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Published Docs", stats["published_documents"])
        col2.metric("Draft Docs", stats["draft_documents"])
        col3.metric(
            "Open Issues",
            stats["open_issues"],
            delta=None if stats["open_issues"] == 0 else f"-{stats['open_issues']}",
            delta_color="inverse",
        )
        col4.metric(
            "Doc Gaps",
            stats["documentation_gaps"],
            delta=None if stats["documentation_gaps"] == 0 else f"-{stats['documentation_gaps']}",
            delta_color="inverse",
        )

        st.divider()

        # System status
        st.subheader("System Status")
        col1, col2 = st.columns(2)
        col1.info(f"**Last Sync:** {stats['last_sync']}")
        col2.success("**Status:** Operational")

        st.divider()

        # Actions
        st.subheader("Actions")
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("🔄 Trigger Sync", use_container_width=True):
                st.info("Sync task queued (placeholder)")

        with col2:
            if st.button("📇 Reindex All", use_container_width=True):
                st.info("Reindex task queued (placeholder)")

        with col3:
            if st.button("🔃 Refresh Stats", use_container_width=True):
                st.rerun()


# =============================================================================
# Governance Dashboard
# =============================================================================

elif page == "📋 Governance":
    st.title("📋 Governance Dashboard")
    st.markdown("Monitor content health and quality")

    # Authentication
    if not st.session_state.authenticated:
        st.warning("Please log in to access the governance dashboard.")
        with st.form("login_form_gov"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

            if submitted:
                if check_auth(username, password):
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    else:
        # Logout button
        if st.sidebar.button("Logout", key="logout_gov"):
            st.session_state.authenticated = False
            st.rerun()

        data = get_governance_data()

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Open Issues", len(data["recent_issues"]))
        col2.metric("Documentation Gaps", len(data["gaps"]))
        col3.metric("Stale Pages", len(data["stale_pages"]))

        st.divider()

        # Tabs for different views
        tab1, tab2, tab3, tab4 = st.tabs([
            "📁 Content by Space",
            "🕳️ Documentation Gaps",
            "📄 Stale Pages",
            "⚠️ Recent Issues",
        ])

        with tab1:
            if data["space_stats"]:
                import pandas as pd
                df = pd.DataFrame(
                    [(s[0], s[1]) for s in data["space_stats"]],
                    columns=["Space", "Pages"],
                )
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.bar_chart(df.set_index("Space"))
            else:
                st.info("No spaces found.")

        with tab2:
            if data["gaps"]:
                for gap in data["gaps"]:
                    with st.expander(f"**{gap.topic}** ({gap.query_count} queries)"):
                        st.markdown(f"**Suggested Title:** {gap.suggested_title or 'N/A'}")
                        if gap.sample_queries:
                            st.markdown("**Sample Queries:**")
                            st.code(gap.sample_queries)
            else:
                st.success("No documentation gaps detected!")

        with tab3:
            if data["stale_pages"]:
                for page in data["stale_pages"]:
                    with st.expander(f"**{page.title}** ({page.space_key})"):
                        st.markdown(f"**Last Updated:** {page.updated_at}")
                        st.markdown(f"**Reason:** {page.staleness_reason or 'Age'}")
            else:
                st.success("No stale pages detected!")

        with tab4:
            if data["recent_issues"]:
                for issue in data["recent_issues"]:
                    severity_color = {
                        "high": "🔴",
                        "medium": "🟡",
                        "low": "🟢",
                    }.get(issue.severity, "⚪")

                    with st.expander(f"{severity_color} **{issue.issue_type}** - {issue.description[:50]}..."):
                        st.markdown(f"**Severity:** {issue.severity}")
                        st.markdown(f"**Page ID:** {issue.page_id}")
                        st.markdown(f"**Description:** {issue.description}")
                        st.markdown(f"**Detected:** {issue.detected_at}")
            else:
                st.success("No open issues!")


# =============================================================================
# Footer
# =============================================================================

st.sidebar.divider()
st.sidebar.caption("Knowledge Base v0.1.0")
