# Method Reference

Complete reference for all JSON-RPC methods available via the WebSocket interface.

> **Note:** `groupId` fields always use **base64-encoded strings** in JSON (decoded to `ay` byte arrays before the DBus call). Timestamps are milliseconds since epoch.

## Error handling and reconnection

Every response has either a `result` or an `error` field. When the bridge loses its DBus
connection to signal-cli, any in-flight call returns an error with `"reconnecting": true`:

```json
{"id": 1, "error": "org.freedesktop.DBus.Error.ServiceUnknown: ...", "reconnecting": true}
{"signal": "Disconnected"}
{"signal": "Reconnected"}
```

**Client behaviour:**

- If `error` has no `reconnecting` field → permanent error (bad params, unknown method). Do not retry.
- If `"reconnecting": true` → the bridge is auto-reconnecting. Wait for `{"signal": "Reconnected"}`, then retry the same call.
- `{"signal": "Disconnected"}` and `{"signal": "Reconnected"}` are broadcast to **all** connected WebSocket clients so passive listeners can track connection state.

## Messaging

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `sendMessage` | `message`, `recipients[]` | `attachments[]` | `{timestamp}` |
| `sendNoteToSelfMessage` | `message` | `attachments[]` | `{timestamp}` |
| `sendMessageReaction` | `emoji`, `remove`, `targetAuthor`, `targetSentTimestamp`, `recipients[]` | - | `{timestamp}` |
| `sendReadReceipt` | `recipient`, `targetSentTimestamps[]` | - | null |
| `sendViewedReceipt` | `recipient`, `targetSentTimestamps[]` | - | null |
| `sendTyping` | `recipient` | `stop` (default false) | null |
| `sendRemoteDeleteMessage` | `targetSentTimestamp`, `recipients[]` | - | `{timestamp}` |
| `sendEndSessionMessage` | `recipients[]` | - | null |
| `sendPaymentNotification` | `receipt` (base64), `note`, `recipient` | - | `{timestamp}` |

## Groups

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `sendGroupMessage` | `message`, `groupId` | `attachments[]` | `{timestamp}` |
| `sendGroupMessageReaction` | `emoji`, `remove`, `targetAuthor`, `targetSentTimestamp`, `groupId` | - | `{timestamp}` |
| `sendGroupRemoteDeleteMessage` | `targetSentTimestamp`, `groupId` | - | `{timestamp}` |
| `sendGroupTyping` | `groupId` | `stop` (default false) | null |
| `createGroup` | `groupName` | `members[]`, `avatar` | `{groupId}` (base64) |
| `listGroups` | - | - | `[{objectPath, groupId, name}]` |
| `getGroupMembers` | `groupId` | - | `[numbers]` |
| `joinGroup` | `inviteURI` | - | null |

## Group Management

These methods operate on a specific group. All require `groupId` (base64).

| Method | Required params | Returns |
|--------|----------------|---------|
| `quitGroup` | `groupId` | null |
| `addGroupMembers` | `groupId`, `recipients[]` | null |
| `removeGroupMembers` | `groupId`, `recipients[]` | null |
| `addGroupAdmins` | `groupId`, `recipients[]` | null |
| `removeGroupAdmins` | `groupId`, `recipients[]` | null |
| `enableGroupLink` | `groupId`, `requiresApproval` | null |
| `disableGroupLink` | `groupId` | null |
| `resetGroupLink` | `groupId` | null |

## Contacts

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `getSelfNumber` | - | - | `{number}` |
| `getContactName` | `number` | - | `{name}` |
| `getContactNumber` | `name` | - | `{numbers[]}` |
| `setContactName` | `number`, `name` | - | null |
| `isContactBlocked` | `number` | - | `{blocked}` |
| `setContactBlocked` | `number`, `block` | - | null |
| `deleteContact` | `number` | - | null |
| `deleteRecipient` | `number` | - | null |
| `isRegistered` | - | `number` or `numbers[]` | `{result}` or `{results[]}` |
| `listNumbers` | - | - | `{numbers[]}` |
| `setExpirationTimer` | `number`, `expiration` (seconds) | - | null |

## Profile

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `updateProfile` | `name` or (`givenName` + `familyName`) | `about`, `aboutEmoji`, `avatar`, `remove` | null |

## Devices

| Method | Required params | Optional params | Returns |
|--------|----------------|-----------------|---------|
| `addDevice` | `deviceUri` | - | null |
| `listDevices` | - | - | `[{objectPath, id, name}]` |
| `sendContacts` | - | - | null |
| `sendSyncRequest` | - | - | null |

## Identity

| Method | Required params | Returns |
|--------|----------------|---------|
| `listIdentities` | - | `[{objectPath, uuid, number}]` |
| `trustIdentity` | `number` | null |
| `trustIdentityVerified` | `number`, `safetyNumber` | null |

## Misc

| Method | Required params | Returns |
|--------|----------------|---------|
| `version` | - | `{version}` |
| `submitRateLimitChallenge` | `challenge`, `captcha` | null |
| `uploadStickerPack` | `stickerPackPath` | `{url}` |
