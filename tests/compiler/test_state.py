"""Tests for compilation state tree."""

from colin.compiler.state import CompilationState, OperationState, Status


class TestOperationState:
    def test_creation_defaults(self) -> None:
        state = OperationState(name="test")
        assert state.name == "test"
        assert state.status == Status.PENDING
        assert state.detail is None
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

    def test_start_sets_processing(self) -> None:
        state = OperationState(name="test")
        assert state.status == Status.PENDING

        state.start()
        assert state.status == Status.PROCESSING

    def test_done_sets_done(self) -> None:
        state = OperationState(name="test")
        state.start()
        state.done()
        assert state.status == Status.DONE

    def test_fail_sets_failed(self) -> None:
        state = OperationState(name="test")
        state.start()
        state.fail()
        assert state.status == Status.FAILED
        assert state.detail is None

    def test_fail_with_error_message(self) -> None:
        state = OperationState(name="test")
        state.start()
        state.fail("Connection timeout")
        assert state.status == Status.FAILED
        assert state.detail == "Connection timeout"

    def test_cached_sets_cached(self) -> None:
        state = OperationState(name="llm:auto:abc")
        state.cached()
        assert state.status == Status.CACHED

    def test_ref_sets_ref(self) -> None:
        state = OperationState(name="ref:other")
        state.ref()
        assert state.status == Status.REF


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
        state = CompilationState()

        doc1 = state.add_document("context/greeting")
        doc2 = state.add_document("context/summary")

        doc1.start()
        ref_op = doc1.child("ref:context/summary")
        ref_op.start()
        ref_op.ref()

        llm_op = doc1.child("llm:auto:abc123", detail="gpt-4o")
        llm_op.start()
        llm_op.done()

        doc1.done()

        doc2.start()
        cached_op = doc2.child("extract:xyz")
        cached_op.cached()
        doc2.done()

        assert doc1.status == Status.DONE
        assert doc2.status == Status.DONE
        assert len(doc1.children) == 2
        assert len(doc2.children) == 1
        assert doc1.children[0].status == Status.REF
        assert doc1.children[1].status == Status.DONE
        assert doc2.children[0].status == Status.CACHED

