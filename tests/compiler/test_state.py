"""Tests for compilation state tree."""

from colin.compiler.state import CompilationState, OperationState, Status


class TestOperationState:
    def test_creation_defaults(self) -> None:
        state = OperationState(name="test")
        assert state.name == "test"
        assert state.status == Status.PENDING
        assert state.detail is None
        assert state.cached is False
        assert state.error is None
        assert state.parent is None
        assert state.children == []

    def test_creation_with_detail(self) -> None:
        state = OperationState(name="llm:auto:abc", detail="gpt-4")
        assert state.detail == "gpt-4"

    def test_child_creates_mutual_attachment(self) -> None:
        parent = OperationState(name="doc")
        child = parent.child("llm:auto:abc")

        assert child.parent is parent
        assert child in parent.children
        assert child.name == "llm:auto:abc"
        assert child.status == Status.PENDING

    def test_child_with_detail(self) -> None:
        parent = OperationState(name="doc")
        child = parent.child("extract:manual", detail="gpt-4o")

        assert child.detail == "gpt-4o"

    def test_multiple_children(self) -> None:
        parent = OperationState(name="doc")
        child1 = parent.child("ref:other")
        child2 = parent.child("llm:auto:123")
        child3 = parent.child("extract:456")

        assert len(parent.children) == 3
        assert parent.children == [child1, child2, child3]

    def test_context_manager_sets_processing_on_enter(self) -> None:
        state = OperationState(name="test")
        assert state.status == Status.PENDING

        with state:
            assert state.status == Status.PROCESSING

    def test_context_manager_sets_done_on_success(self) -> None:
        state = OperationState(name="test")
        with state:
            pass
        assert state.status == Status.DONE

    def test_context_manager_sets_failed_on_exception(self) -> None:
        state = OperationState(name="test")
        try:
            with state:
                raise ValueError("Something went wrong")
        except ValueError:
            pass
        assert state.status == Status.FAILED
        assert state.error == "Something went wrong"

    def test_context_manager_propagates_exception(self) -> None:
        state = OperationState(name="test")
        raised = False
        try:
            with state:
                raise RuntimeError("test error")
        except RuntimeError:
            raised = True
        assert raised

    def test_mark_cached(self) -> None:
        state = OperationState(name="llm:auto:abc")
        state.mark_cached()
        assert state.status == Status.DONE
        assert state.cached is True


class TestCompilationState:
    def test_empty_state(self) -> None:
        state = CompilationState()
        assert state.documents == {}

    def test_add_document(self) -> None:
        state = CompilationState()
        doc_state = state.add_document("context/greeting")

        assert doc_state.name == "context/greeting"
        assert doc_state.status == Status.PENDING
        assert "context/greeting" in state.documents
        assert state.documents["context/greeting"] is doc_state

    def test_add_multiple_documents(self) -> None:
        state = CompilationState()
        doc1 = state.add_document("a")
        doc2 = state.add_document("b")
        doc3 = state.add_document("c")

        assert len(state.documents) == 3
        assert state.documents["a"] is doc1
        assert state.documents["b"] is doc2
        assert state.documents["c"] is doc3

    def test_get_document_found(self) -> None:
        state = CompilationState()
        doc_state = state.add_document("test")

        result = state.get_document("test")
        assert result is doc_state

    def test_get_document_not_found(self) -> None:
        state = CompilationState()
        result = state.get_document("nonexistent")
        assert result is None

    def test_full_workflow(self) -> None:
        """Test a realistic compilation workflow with context managers."""
        state = CompilationState()

        doc1 = state.add_document("context/greeting")
        doc2 = state.add_document("context/summary")

        # Compile doc1 with a ref and an LLM call
        with doc1:
            with doc1.child("ref:context/summary"):
                pass  # Ref resolution

            with doc1.child("llm:auto:abc123", detail="gpt-4o"):
                pass  # LLM call

        # Compile doc2 with a cached operation
        with doc2:
            cached_op = doc2.child("extract:xyz")
            cached_op.mark_cached()

        assert doc1.status == Status.DONE
        assert doc2.status == Status.DONE
        assert len(doc1.children) == 2
        assert len(doc2.children) == 1
        assert doc1.children[0].status == Status.DONE  # ref completed
        assert doc1.children[1].status == Status.DONE  # llm completed
        assert doc2.children[0].status == Status.DONE
        assert doc2.children[0].cached is True

    def test_mcp_operations_tracked_like_refs(self) -> None:
        """MCP resource access appears as child operations like refs."""
        state = CompilationState()

        doc = state.add_document("context/with_mcp")

        with doc:
            # Ref operation
            with doc.child("ref:other_doc"):
                pass

            # MCP access (also completes with DONE status)
            with doc.child("mcp:greeter", detail="colin://hello"):
                pass

        assert len(doc.children) == 2
        assert doc.children[0].name == "ref:other_doc"
        assert doc.children[0].status == Status.DONE
        assert doc.children[1].name == "mcp:greeter"
        assert doc.children[1].detail == "colin://hello"
        assert doc.children[1].status == Status.DONE
