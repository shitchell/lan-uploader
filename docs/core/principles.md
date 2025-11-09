# 💡 Project Principles

**Purpose:** This document defines the "How." It is the strategic guide for making design and development decisions, especially when faced with trade-offs. These are the rules that shape the product's character and function.

---

### ⛓️ Project Constraints
What are the project's constraints (e.g., hardware, software stack, time, resources)?

- [x] Must run offline (within a LAN).
- [x] Must work on low-power hardware (e.g., Raspberry Pi).
- [x] Must have minimal external dependencies.
- [x] Resource constraint: Must be maintainable by a single developer or a small team.

---

### 😊 UX Feel
How should the user experience *feel*?

*   Simple and fast, like a utility that gets out of your way.
*   Reliable and unobtrusive, inspiring confidence that your files are handled safely.
*   The UI should feel modern and responsive, but functionality and reliability take priority over aesthetics.

---

### ✨ Simplicity vs. Features
When faced with a choice between adding a feature and maintaining simplicity, which do we prefer?

*   We prefer features and flexibility. The goal is to build a powerful and extensible tool. However, new features must be well-planned and align with the project's core identity.

---

### 🔌 Extensibility vs. Focus
Is it more important for the project to be extensible or to be a complete, focused tool?

*   We favor a swiss army knife tool that is highly extensible. Where extensibility is planned or reasonable to expect, its implementation is critical:
    *   **"Drop-In" Extensibility:** New functionality should be added with minimal changes to surrounding code. The ideal is a "drop-in" mechanism, such as a new function being automatically detected, a new event handler being registered, or a plugin file being loaded from a specific directory.
    *   **Interface-Driven Design for Pivots:** Where we anticipate pivoting from a simple solution to a more optimized one later (e.g., moving from filesystem search to a database), the initial implementation must be behind a clear interface or abstraction layer. This ensures that the surrounding code does not need to change when the underlying implementation is upgraded.

---

### 📦 Dependencies
What is our stance on third-party dependencies? What is the criteria for adding a new one?

*   Dependencies are acceptable if they meet the following strict criteria:
    *   They must be mature, well-audited frameworks heavily used in industry.
    *   They must pass security checks and be locked to a specific, vetted version.
    *   They must provide core, strongly desired features that would be significantly more complex to build and maintain custom.
    *   Crucially, they must make the code easier to read and audit than a custom-rolled solution.

---

### 🛡️ Security Philosophy
What is our baseline philosophy for security?

*   Secure by default. Assume a trusted network, but protect against all common web vulnerabilities.

---

### 🧪 Testing Philosophy
What is our philosophy on testing? What types of tests do we prioritize?

*   We employ a rigorous, multi-layered testing strategy:
    *   **E2E First:** Whenever possible, an end-to-end test using real data should be created first. This test defines the feature's success criteria and informs the creation of mock data.
    *   **Comprehensive Unit Tests:** Every unit of code (function, class) should have a corresponding unit test.
    *   **Mirrored Mock/Real Tests:** Every test that uses mock data must have a corresponding E2E test that uses real data to validate the mock's accuracy.
    *   If the infrastructure isn't in place to support an E2E-first approach, the implementation plan must be re-assessed and potentially re-ordered.

---

### 🎨 Design Patterns & Standards
Are there favored code or UI design patterns? If yes, in what contexts are different patterns favored?

This is broken down into high-level architectural choices and universal coding standards.

#### Contextual Architectural Patterns
*   **Event-Driven Architecture:**
    *   *Context:* For the web application's request/response cycle. The migration to FastAPI, an ASGI framework, leans into this pattern for handling asynchronous web traffic efficiently.
*   **Database Abstraction:**
    *   *Context:* Used for the file indexing and search feature (`models.py`). This was explicitly chosen to allow swapping out SQLite for a more powerful database in the future without a major refactor.

#### Universal Coding Standards
*   **Aggressive Parameterization:**
    *   *Rule:* If it is even remotely possible that a feature or setting might not be desired in some use-case, or could be useful to adjust, it **must** be made configurable via command-line arguments and the configuration file.
*   **Naming Conventions:**
    *   *Rule:* Python functions and variables use `snake_case`, classes use `PascalCase`.
*   **Documentation:**
    *   *Rule:* Public functions should have docstrings. The migration to FastAPI with its automatic OpenAPI documentation shows a strong commitment to clear, documented APIs.