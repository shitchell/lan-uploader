# 🧭 Project Identity

**Purpose:** This document defines the project's "North Star"—its fundamental purpose, audience, and boundaries. It should be the most stable document. If this document changes, the project has fundamentally pivoted.

---

### 🎯 Overarching Goal
What is the overarching goal of the project? What value does it aim to provide or what new capability does it enable?

*   To provide a simple, fast, and private way for individuals and small teams to transfer and manage files within their own local network.
*   To enable users to easily move files, especially from mobile devices, to a central server without relying on public cloud services.

---

### 👥 Target Audience
Who is the primary target audience?

*   Home users, developers, hobbyists, and small teams.
*   Anyone who values data privacy and wants to self-host a simple utility for managing files on their own network.

---

### 🚫 Non-Audience
Is there anyone who is explicitly *not* part of the target audience?

*   Enterprise users requiring SSO, audit logs, and complex permissions.
*   Users who need to share files over the public internet.

---

### 📌 Non-Negotiable Goals
Are there any absolute, non-negotiable goals?

*   The application must operate entirely within the user's own network.
*   The core functionality must be intuitive enough to be used without a manual.
*   Security against common web vulnerabilities (like path traversal) is mandatory.

---

### 🗺️ Project Boundaries
What is this project explicitly *not* trying to be?

*   This project is not a Dropbox or Google Drive replacement.
*   It is not a full-featured Network Attached Storage (NAS) management interface.
*   It is not a public file-sharing platform.