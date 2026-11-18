# 🛠️ HelpDesk Lite — User Guide
**IT Support Assistant | Nimbus Analytics**

Welcome to **HelpDesk Lite**. This assistant helps the Nimbus Analytics IT Support team triage incoming employee requests faster by automatically cross-referencing company IT policies, the employee directory, application dependencies, and active outage notices.

---

## 🎯 How It Helps You
When an employee reports an issue via chat or email, you no longer need to manually search across multiple disconnected systems. **HelpDesk Lite** investigates the issue and recommends the appropriate next step—while keeping **you** in full control of every action that modifies an account or logs a ticket.

---

## 📋 How to Use HelpDesk Lite

### 1. Paste the Employee Request
Start by pasting the employee's message directly into the chat.  
> **Example:** *"I can't connect to the VPN since yesterday afternoon and I need the finance reports before Friday. Can you reset my access?"*

### 2. Provide Missing Details (If Prompted)
HelpDesk Lite never guesses missing facts. If essential details—such as the employee's **office location** or **device/OS**—are missing from the initial message, the assistant will pause and ask you to clarify them before proceeding.

### 3. Review the Proposed Action & Sources
Once all required details are available, the assistant checks active service incidents and relevant IT policies, then proposes **one specific action**:

| Code | Action | When It Is Proposed |
| :--- | :--- | :--- |
| **`A`** | **Answer from policy only** | The issue can be resolved by following standard IT guidance without changing any system or account. |
| **`B`** | **Link to an open outage** | An active service outage (direct or upstream dependency) explains the issue. *Note: Linking to an outage always takes priority over resetting credentials.* |
| **`C`** | **Reset credentials** | The request qualifies for an access/password reset under current IT policy and no related service outage is active. |
| **`D`** | **Open a new ticket** | A standard support ticket is required for further tracking and troubleshooting. |
| **`E`** | **Escalate to an engineer** | The request involves a complex issue or an account/directory anomaly (such as missing team membership) requiring manual investigation. |

### 4. Approve or Reject
Before any account change or ticket creation takes place, the assistant pauses and presents an **Approval Card** showing:
- The proposed action and reasoning.
- The exact **Policy Document ID** and **Effective Date** used.
- Any linked **Outage ID** and affected service dependencies.
- A preview of the exact record that will be executed.

Click **✅ Approve & Execute** to run the action, or **❌ Reject** to cancel it immediately without making any system changes.

---

## 💬 Asking Follow-Up Questions
After reviewing or completing a request, you can ask follow-up questions in the same chat to get more context:
- *"Why didn't you reset the password?"*
- *"Which other teams are affected by this outage?"*
- *"Which policy did you base this on?"*

---

## 🛡️ Built-In Safeguards
- **Human-in-the-Loop Control:** Nothing that changes an account or creates a ticket is ever executed without your explicit approval.
- **Up-to-Date Policy Compliance:** When multiple versions of an IT policy exist, HelpDesk Lite automatically applies the version with the most recent **Effective Date** and cites it in every response.
- **Session Recovery:** If your browser disconnects or the system restarts while an approval is pending, your session is automatically preserved. Simply reconnect or type *"Continue the request I opened before the restart"* to pick up right where you left off—approved actions are never executed twice.