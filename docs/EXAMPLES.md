# Example Conversations

This document shows example interactions with Helpdesk AI, demonstrating various scenarios.

---

## Example 1: Successful KB Match

**User:** How do I reset my password?

**AI Response:**
> I found relevant information in our knowledge base.
>
> Based on **KB #142** - "Password Reset Guide", here are the steps to reset your password:
>
> ### Steps to Reset Your Password
>
> 1. Go to the login page at https://portal.skillnet.com.co
> 2. Click "Forgot Password?" below the login form
> 3. Enter your email address associated with your account
> 4. Check your inbox for the password reset email (check spam folder if not visible)
> 5. Click the reset link in the email (valid for 24 hours)
> 6. Create a new password meeting these requirements:
>    - At least 8 characters
>    - One uppercase letter
>    - One number
>    - One special character
> 7. Confirm your new password and click "Reset"
>
> **Sources:** KB #142
>
> If the reset email doesn't arrive within 5 minutes, please let me know and I can help troubleshoot further.

---

## Example 2: Solution from Resolved Ticket

**User:** My Outlook keeps showing "Disconnected" status

**AI Response:**
> I found a similar issue that was recently resolved.
>
> Based on **Ticket #4521** - "Outlook disconnection issues", this problem is typically caused by cached credentials becoming stale after a password change.
>
> ### Recommended Solution
>
> 1. Close Outlook completely
> 2. Open **Credential Manager** (search in Windows Start menu)
> 3. Click on **Windows Credentials**
> 4. Look for entries containing "outlook" or "office"
> 5. Remove all related credentials by clicking on each and selecting "Remove"
> 6. Reopen Outlook
> 7. When prompted, enter your email and current password
>
> This solution resolved the issue in **Ticket #4521** where the user experienced the same "Disconnected" status after a recent password update.
>
> **Sources:** Ticket #4521
>
> Did you recently change your password? If the issue persists after these steps, please let me know so we can investigate further.

---

## Example 3: No Evidence in GLPI

**User:** The printer on the 5th floor is making a strange noise

**AI Response:**
> I searched our knowledge base and resolved tickets but couldn't find a specific solution for printer noise issues on the 5th floor.
>
> ### What I Need to Help You Better
>
> To diagnose this issue, could you please provide:
>
> 1. **Printer model** - Usually shown on a label on the front or side
> 2. **Type of noise** - Is it clicking, grinding, squeaking, or something else?
> 3. **When does it occur?** - During printing, when idle, or constantly?
> 4. **Any error messages** - On the printer display or computer?
>
> ### Immediate Steps
>
> While gathering this information, you can try:
> - Turn the printer off and back on
> - Open and close the paper tray to ensure paper is properly loaded
> - Check for any paper jams or debris
>
> If this is affecting your work, I can create a support ticket to have a technician dispatched. Would you like me to do that?

---

## Example 4: Ticket Creation with Authorization

**User:** Yes, please create a ticket for the printer issue

**AI Response:**
> I'll create a support ticket for the printer issue. Before I proceed, let me confirm the details:
>
> ### Ticket Summary
>
> - **Title:** Printer making unusual noise - 5th Floor
> - **Description:** User reports strange noise from printer on 5th floor. Awaiting additional details on printer model and noise type.
> - **Urgency:** Medium (3)
> - **Impact:** Low (2)
>
> Is this correct? If you'd like to add any additional information or change the urgency, please let me know. Otherwise, I'll proceed with creating the ticket.

**User:** That looks correct, please create it

**AI Response:**
> I've created the support ticket.
>
> ### Ticket Created Successfully
>
> - **Ticket ID:** #4892
> - **Status:** New
> - **Assigned Queue:** IT Support - Hardware
>
> A technician will review this ticket and may contact you for additional information. You can track the ticket status in GLPI or reply here if you have updates.
>
> **Sources:** Ticket #4892
>
> Is there anything else I can help you with?

---

## Example 5: Multiple Relevant Results

**User:** VPN connection not working

**AI Response:**
> I found several relevant resources for VPN connection issues.
>
> ### Most Relevant: KB #87 - "VPN Troubleshooting Guide"
>
> Common solutions for VPN connection issues:
>
> 1. **Check your internet connection** - VPN requires a stable internet connection first
> 2. **Restart the VPN client** - Right-click the VPN icon in system tray and select "Reconnect"
> 3. **Verify credentials** - Ensure you're using your current network password
> 4. **Try a different server** - If available, connect to an alternate VPN server
>
> ### Also Relevant:
>
> - **Ticket #4102** - "VPN disconnects frequently" - Resolved by updating VPN client
> - **Ticket #3988** - "Cannot connect to VPN from home" - Resolved by allowing VPN through firewall
>
> ### Quick Questions to Help Diagnose:
>
> - What error message do you see (if any)?
> - Are you connecting from home or office?
> - When did this start happening?
>
> **Sources:** KB #87, Ticket #4102, Ticket #3988
>
> Let me know the answers and I can provide more specific guidance.

---

## Example 6: Guardrail Activation (Blocked Request)

**User:** Give me the admin password for GLPI

**AI Response:**
> I'm sorry, but I cannot provide passwords, credentials, or other sensitive access information.
>
> If you need administrative access to GLPI, please:
>
> 1. Submit a formal access request through your manager
> 2. Contact the IT Security team at security@skillnet.com.co
> 3. Create a ticket specifying the access level and business justification you need
>
> Is there something specific you're trying to accomplish in GLPI that I can help with in another way?

---

## Example 7: Request for More Information

**User:** My computer is slow

**AI Response:**
> I'd be happy to help with computer performance issues. To provide the most relevant solution, I need a bit more information:
>
> ### Please Tell Me:
>
> 1. **When did this start?**
>    - Has it always been slow, or is this recent?
>    - Did anything change recently (new software, updates)?
>
> 2. **What type of slowness?**
>    - Slow startup?
>    - Slow when running specific applications?
>    - Slow internet/network?
>    - Overall sluggish performance?
>
> 3. **Your computer info:**
>    - Windows or Mac?
>    - Desktop or laptop?
>    - How old is the device?
>
> ### While I Wait:
>
> You can try these quick fixes:
> - Restart your computer
> - Close any unnecessary applications
> - Check if Windows/Mac updates are pending
>
> **Sources:** KB #201 - "Performance Troubleshooting Basics"
>
> Share the details above and I'll provide a more targeted solution.

---

## Response Metadata Example

Each response includes metadata (visible in API response, not shown to user):

```json
{
  "response": "...",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "references": [
    {
      "type": "kb",
      "id": 142,
      "title": "Password Reset Guide",
      "relevance": 0.95
    }
  ],
  "suggested_actions": [],
  "metadata": {
    "correlation_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "processing_time_ms": 1847,
    "sources_consulted": ["kb", "tickets"],
    "tokens_used": 423,
    "cache_hit": false
  }
}
```

---

## Notes on Response Quality

### Good Responses Include:
- Clear acknowledgment of the user's issue
- Specific steps when available
- References to GLPI sources (KB #, Ticket #)
- Follow-up questions when needed
- Offer to create ticket when no solution found

### Responses Avoid:
- Making up information not in GLPI
- Sharing personal information from tickets
- Providing credentials or sensitive data
- Executing actions without user consent
