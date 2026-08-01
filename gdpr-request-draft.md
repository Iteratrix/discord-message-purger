> **Template.** Fill in every `[BRACKETED]` field before sending. Do not commit a
> filled-in copy to version control — it contains your account identifiers.

**To:** privacy@discord.com
**Subject:** GDPR Article 17 — Request for Complete Erasure of Personal Data

---

To the Discord Privacy Team,

I am writing to exercise my right to erasure ("right to be forgotten") under Article 17 of the General Data Protection Regulation (GDPR).

**Account details:**
- Username: [YOUR USERNAME]
- User ID: [YOUR USER ID]
- Account email: [YOUR ACCOUNT EMAIL]

I am in the process of deleting my Discord account and request the complete erasure of all personal data Discord holds about me. Before initiating account deletion, I have taken the following steps to remove my own data:

1. Requested and received my GDPR data package export.
2. Used the data package to identify and delete all messages I authored — approximately [MESSAGE COUNT] messages across [CHANNEL COUNT] channels, including DMs, group DMs, server channels, and threads.
3. Removed approximately [REACTION COUNT] reactions I placed on other users' messages.
4. Cleared my profile information (avatar, banner, bio, pronouns, display name).
5. Left all servers and removed all friend/block relationships.

**Data I was unable to delete and request Discord erase:**

Despite exhaustive effort, approximately [FINAL FAILURE COUNT] messages I authored remain in channels and servers I no longer have access to (servers I have left, been removed from, or that have restricted permissions). I am unable to delete these messages via the API because Discord returns HTTP 400/403 errors for these channels. A complete list of affected channel IDs and message IDs is attached as `failed_messages.csv`.

These messages are my personal data and I request their erasure under Article 17. To be clear: I am providing the specific message IDs and channel IDs upfront so that there is no ambiguity about which data requires deletion.

**Scope of erasure request:**

I request the erasure of all personal data Discord holds about me, including but not limited to:

- **Message content and metadata** in channels I can no longer access (IDs attached)
- **Attachments and uploaded media** — files I uploaded that may persist on Discord's CDN after message deletion
- **Email address and phone number** — I understand Discord's policy retains these for 180 days after account deletion; I request immediate erasure as no legitimate purpose survives account deletion
- **IP addresses and login history**
- **Device and browser information**
- **Activity and analytics data** (usage statistics, event logs, modeling data, frecency data)
- **Trust & Safety records** — any data held for moderation purposes
- **Payment and billing history**
- **Voice and video data** — any recordings or metadata from voice/video sessions
- **Search history and frecency data**
- **Data used for AI/ML training** — Discord's September 2025 privacy policy update permits retention of public posts for up to 2 years for model training; I request deletion from any such training datasets
- **Any data shared with or held by third parties** on Discord's behalf

I request that this erasure extend to all systems, including production databases, backup systems, data warehouses, analytics pipelines, and any third-party processors. Per Article 17(2), where Discord has made the personal data public, I request that you take reasonable steps to inform other controllers processing the data that I have requested its erasure. Per Article 19, I request that you notify all recipients to whom the data has been disclosed.

**Preemptive responses to anticipated objections:**

1. **"Anonymization is sufficient"** — Relabeling my account as "Deleted User" while retaining my message content does not constitute erasure or effective anonymization. My messages contain personal information (life events, opinions, locations, relationships) that remains identifiable in context regardless of whether the author label is removed. The EDPB CEF 2025 report on right to erasure specifically identified "ineffective anonymization or pseudonymization instead of permanent deletion, creating re-identification risks" as a compliance failure.

2. **"Other users have a legitimate interest in conversation context"** — This does not override my Article 17 right. The data was originally processed on the basis of my consent and/or contract, both of which I am withdrawing. Article 17(1)(b) and (c) apply. Conversation context is a convenience, not a legal basis for continued processing of my personal data.

3. **"Please provide message IDs"** — I am providing them proactively as an attached file. This removes any justification for delay.

**Legal basis:**

Under GDPR Article 17(1), I have the right to obtain erasure of personal data without undue delay where:
- (a) the personal data are no longer necessary in relation to the purposes for which they were collected — I am deleting my account;
- (b) I withdraw consent — I withdraw any consent previously given for data processing;
- (c) I object to processing under Article 21(1) and there are no overriding legitimate grounds;
- (d) the personal data have been unlawfully processed — retaining my authored messages in channels I cannot access or delete from, without providing a mechanism for erasure, may constitute processing without a valid legal basis.

Under Article 12(3), you are required to respond to this request without undue delay and in any event within one month.

I note that Discord has previously been sanctioned by the CNIL (November 2022, EUR 800,000) for violations including failure to maintain data retention policies and retaining inactive user accounts for years without justification. I trust that Discord's data practices have improved since that sanction.

If you believe any exemption under Article 17(3) applies to any subset of this data, please specify exactly which data, which exemption, and your justification. A blanket invocation of exemptions without specificity does not satisfy Article 12(4).

If I do not receive a substantive response within 30 days, I will file a complaint with my national Data Protection Authority.

Please confirm in writing once the erasure is complete.

Regards,
[YOUR NAME]
