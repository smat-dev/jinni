# Plan: GitHub Actions CI Tests

**1. Goal:** Implement GitHub Actions workflows to automatically run the project's `pytest` suite on Linux and Windows environments for Python 3.11 and 3.12 (latest stable).

**2. Workflow File:** Create `.github/workflows/test.yml`.

**3. Triggers:**
   *   On every `push` to any branch.

**4. Job: `build_and_test`**
   *   **Strategy Matrix:**
        *   `os`: [`ubuntu-latest`, `windows-latest`]
        *   `python-version`: [`3.11`, `3.12`]
   *   **Steps:**
        1.  `actions/checkout@v4`: Checkout repository code.
        2.  `actions/setup-python@v5`: Setup Python `matrix.python-version`.
        3.  `pip install uv`: Install the `uv` tool.
        4.  `uv pip install .[dev]`: Install project dependencies using `pyproject.toml`.
        5.  `uv run pytest`: Execute the test suite.

**5. Workflow Structure (Mermaid Diagram):**

```mermaid
graph TD
    A[Trigger: Push to any branch] --> B{Job: build_and_test};
    B --> C{Matrix: OS=[ubuntu-latest, windows-latest], Python=[3.11, 3.12]};
    C --> D[Step 1: Checkout Code (actions/checkout@v4)];
    D --> E[Step 2: Setup Python (actions/setup-python@v5)];
    E --> F[Step 3: Install uv (pip install uv)];
    F --> G[Step 4: Install Dependencies (uv pip install .[dev])];
    G --> H[Step 5: Run Tests (uv run pytest)];
```

**6. Next Step:** Switch to Code mode to implement the workflow file.