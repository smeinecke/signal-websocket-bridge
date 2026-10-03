"""Method dispatching from WebSocket JSON-RPC to DBus calls.

Each handler invokes `BoundInterface.call(member, signature, body)` with the
method's DBus input signature. Signatures are explicit rather than
introspection-derived because signal-cli dispatches methods on interfaces
that are not always declared in introspection data.
"""

import asyncio
from enum import Enum
from typing import Any, Callable

from swb.types import (
    dbus_to_native,
    to_bytes,
    to_int64,
    to_int64_array,
    to_string_array,
    validate_attachments,
)

# DBus calls against signal-cli should never take this long; a timeout
# means the service is hung, which is treated as a lost connection.
CALL_TIMEOUT = 30.0


class Method(Enum):
    """JSON-RPC method names supported by the bridge."""

    # Messaging
    SEND_MESSAGE = "sendMessage"
    SEND_NOTE_TO_SELF_MESSAGE = "sendNoteToSelfMessage"
    SEND_MESSAGE_REACTION = "sendMessageReaction"
    SEND_READ_RECEIPT = "sendReadReceipt"
    SEND_VIEWED_RECEIPT = "sendViewedReceipt"
    SEND_TYPING = "sendTyping"
    SEND_REMOTE_DELETE_MESSAGE = "sendRemoteDeleteMessage"
    SEND_END_SESSION_MESSAGE = "sendEndSessionMessage"
    SEND_PAYMENT_NOTIFICATION = "sendPaymentNotification"

    # Groups (main interface)
    SEND_GROUP_MESSAGE = "sendGroupMessage"
    SEND_GROUP_MESSAGE_REACTION = "sendGroupMessageReaction"
    SEND_GROUP_REMOTE_DELETE_MESSAGE = "sendGroupRemoteDeleteMessage"
    SEND_GROUP_TYPING = "sendGroupTyping"
    CREATE_GROUP = "createGroup"
    LIST_GROUPS = "listGroups"
    GET_GROUP_MEMBERS = "getGroupMembers"
    JOIN_GROUP = "joinGroup"

    # Group sub-interface
    QUIT_GROUP = "quitGroup"
    ADD_GROUP_MEMBERS = "addGroupMembers"
    REMOVE_GROUP_MEMBERS = "removeGroupMembers"
    ADD_GROUP_ADMINS = "addGroupAdmins"
    REMOVE_GROUP_ADMINS = "removeGroupAdmins"
    ENABLE_GROUP_LINK = "enableGroupLink"
    DISABLE_GROUP_LINK = "disableGroupLink"
    RESET_GROUP_LINK = "resetGroupLink"

    # Contacts
    GET_SELF_NUMBER = "getSelfNumber"
    GET_CONTACT_NAME = "getContactName"
    GET_CONTACT_NUMBER = "getContactNumber"
    SET_CONTACT_NAME = "setContactName"
    IS_CONTACT_BLOCKED = "isContactBlocked"
    SET_CONTACT_BLOCKED = "setContactBlocked"
    DELETE_CONTACT = "deleteContact"
    DELETE_RECIPIENT = "deleteRecipient"
    IS_REGISTERED = "isRegistered"
    LIST_NUMBERS = "listNumbers"
    SET_EXPIRATION_TIMER = "setExpirationTimer"

    # Profile
    UPDATE_PROFILE = "updateProfile"

    # Devices
    ADD_DEVICE = "addDevice"
    LIST_DEVICES = "listDevices"
    SEND_CONTACTS = "sendContacts"
    SEND_SYNC_REQUEST = "sendSyncRequest"

    # Misc
    VERSION = "version"
    SUBMIT_RATE_LIMIT_CHALLENGE = "submitRateLimitChallenge"
    UPLOAD_STICKER_PACK = "uploadStickerPack"

    # Identity
    LIST_IDENTITIES = "listIdentities"
    TRUST_IDENTITY = "trustIdentity"
    TRUST_IDENTITY_VERIFIED = "trustIdentityVerified"


class MethodDispatcher:
    """Dispatches JSON-RPC method calls to signal-cli DBus interface.

    Resolves the interface through the client on every call so
    reconnections are transparent - stale references are never held
    across a disconnect.
    """

    def __init__(self, client, account: str | None = None):
        """
        Args:
            client:  SignalClient providing bus access and interface resolution
            account: account number this dispatcher is bound to (or None for default)
        """
        self._client = client
        self._account = account
        self._iface: Any = None
        self._handlers: dict[Method, Callable] = {
            # Messaging
            Method.SEND_MESSAGE: self._send_message,
            Method.SEND_NOTE_TO_SELF_MESSAGE: self._send_note_to_self,
            Method.SEND_MESSAGE_REACTION: self._send_message_reaction,
            Method.SEND_READ_RECEIPT: self._send_read_receipt,
            Method.SEND_VIEWED_RECEIPT: self._send_viewed_receipt,
            Method.SEND_TYPING: self._send_typing,
            Method.SEND_REMOTE_DELETE_MESSAGE: self._send_remote_delete,
            Method.SEND_END_SESSION_MESSAGE: self._send_end_session,
            Method.SEND_PAYMENT_NOTIFICATION: self._send_payment_notification,
            # Groups (main interface)
            Method.SEND_GROUP_MESSAGE: self._send_group_message,
            Method.SEND_GROUP_MESSAGE_REACTION: self._send_group_message_reaction,
            Method.SEND_GROUP_REMOTE_DELETE_MESSAGE: self._send_group_remote_delete,
            Method.SEND_GROUP_TYPING: self._send_group_typing,
            Method.CREATE_GROUP: self._create_group,
            Method.LIST_GROUPS: self._list_groups,
            Method.GET_GROUP_MEMBERS: self._get_group_members,
            Method.JOIN_GROUP: self._join_group,
            # Group sub-interface
            Method.QUIT_GROUP: self._quit_group,
            Method.ADD_GROUP_MEMBERS: self._add_group_members,
            Method.REMOVE_GROUP_MEMBERS: self._remove_group_members,
            Method.ADD_GROUP_ADMINS: self._add_group_admins,
            Method.REMOVE_GROUP_ADMINS: self._remove_group_admins,
            Method.ENABLE_GROUP_LINK: self._enable_group_link,
            Method.DISABLE_GROUP_LINK: self._disable_group_link,
            Method.RESET_GROUP_LINK: self._reset_group_link,
            # Contacts
            Method.GET_SELF_NUMBER: self._get_self_number,
            Method.GET_CONTACT_NAME: self._get_contact_name,
            Method.GET_CONTACT_NUMBER: self._get_contact_number,
            Method.SET_CONTACT_NAME: self._set_contact_name,
            Method.IS_CONTACT_BLOCKED: self._is_contact_blocked,
            Method.SET_CONTACT_BLOCKED: self._set_contact_blocked,
            Method.DELETE_CONTACT: self._delete_contact,
            Method.DELETE_RECIPIENT: self._delete_recipient,
            Method.IS_REGISTERED: self._is_registered,
            Method.LIST_NUMBERS: self._list_numbers,
            Method.SET_EXPIRATION_TIMER: self._set_expiration_timer,
            # Profile
            Method.UPDATE_PROFILE: self._update_profile,
            # Devices
            Method.ADD_DEVICE: self._add_device,
            Method.LIST_DEVICES: self._list_devices,
            Method.SEND_CONTACTS: self._send_contacts,
            Method.SEND_SYNC_REQUEST: self._send_sync_request,
            # Misc
            Method.VERSION: self._version,
            Method.SUBMIT_RATE_LIMIT_CHALLENGE: self._submit_rate_limit,
            Method.UPLOAD_STICKER_PACK: self._upload_sticker_pack,
            # Identity
            Method.LIST_IDENTITIES: self._list_identities,
            Method.TRUST_IDENTITY: self._trust_identity,
            Method.TRUST_IDENTITY_VERIFIED: self._trust_identity_verified,
        }

    @property
    def signal_interface(self) -> Any:
        """The current bound interface; only valid inside dispatch()."""
        if self._iface is None:
            raise RuntimeError("dispatch() has not resolved an interface")
        return self._iface

    async def dispatch(self, method_name: str, params: dict):
        """Dispatch JSON-RPC method call to appropriate handler."""
        try:
            method = Method(method_name)
        except ValueError:
            raise ValueError(f"unknown method '{method_name}'")

        handler = self._handlers.get(method)
        if not handler:
            raise ValueError(f"no handler for method '{method_name}'")

        try:
            self._iface = self._client.interface(self._account)
            return await asyncio.wait_for(handler(params), timeout=CALL_TIMEOUT)
        except Exception as exc:
            self._client.note_error(exc)
            raise

    # -------------------------------------------------------------------------
    # Messaging handlers
    # -------------------------------------------------------------------------

    async def _send_message(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = await self.signal_interface.call("sendMessage", "sasas", [params["message"], to_string_array(attachments), params["recipients"]])
        return {"timestamp": int(ts)}

    async def _send_note_to_self(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = await self.signal_interface.call("sendNoteToSelfMessage", "sas", [params["message"], to_string_array(attachments)])
        return {"timestamp": int(ts)}

    async def _send_message_reaction(self, params: dict) -> dict:
        ts = await self.signal_interface.call(
            "sendMessageReaction",
            "sbsxas",
            [
                params["emoji"],
                bool(params["remove"]),
                params["targetAuthor"],
                to_int64(params["targetSentTimestamp"]),
                params["recipients"],
            ],
        )
        return {"timestamp": int(ts)}

    async def _send_read_receipt(self, params: dict) -> None:
        await self.signal_interface.call("sendReadReceipt", "sax", [params["recipient"], to_int64_array(params["targetSentTimestamps"])])
        return None

    async def _send_viewed_receipt(self, params: dict) -> None:
        await self.signal_interface.call("sendViewedReceipt", "sax", [params["recipient"], to_int64_array(params["targetSentTimestamps"])])
        return None

    async def _send_typing(self, params: dict) -> None:
        await self.signal_interface.call("sendTyping", "sb", [params["recipient"], bool(params.get("stop", False))])
        return None

    async def _send_remote_delete(self, params: dict) -> dict:
        ts = await self.signal_interface.call("sendRemoteDeleteMessage", "xas", [to_int64(params["targetSentTimestamp"]), params["recipients"]])
        return {"timestamp": int(ts)}

    async def _send_end_session(self, params: dict) -> None:
        await self.signal_interface.call("sendEndSessionMessage", "as", [params["recipients"]])
        return None

    async def _send_payment_notification(self, params: dict) -> dict:
        ts = await self.signal_interface.call("sendPaymentNotification", "ayss", [to_bytes(params["receipt"]), params["note"], params["recipient"]])
        return {"timestamp": int(ts)}

    # -------------------------------------------------------------------------
    # Groups (main interface) handlers
    # -------------------------------------------------------------------------

    async def _send_group_message(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = await self.signal_interface.call("sendGroupMessage", "sasay", [params["message"], to_string_array(attachments), to_bytes(params["groupId"])])
        return {"timestamp": int(ts)}

    async def _send_group_message_reaction(self, params: dict) -> dict:
        ts = await self.signal_interface.call(
            "sendGroupMessageReaction",
            "sbsxay",
            [
                params["emoji"],
                bool(params["remove"]),
                params["targetAuthor"],
                to_int64(params["targetSentTimestamp"]),
                to_bytes(params["groupId"]),
            ],
        )
        return {"timestamp": int(ts)}

    async def _send_group_remote_delete(self, params: dict) -> dict:
        ts = await self.signal_interface.call("sendGroupRemoteDeleteMessage", "xay", [to_int64(params["targetSentTimestamp"]), to_bytes(params["groupId"])])
        return {"timestamp": int(ts)}

    async def _send_group_typing(self, params: dict) -> None:
        await self.signal_interface.call("sendGroupTyping", "ayb", [to_bytes(params["groupId"]), bool(params.get("stop", False))])
        return None

    async def _create_group(self, params: dict) -> dict:
        group_id = await self.signal_interface.call("createGroup", "sass", [params["groupName"], params.get("members", []), params.get("avatar", "")])
        return {"groupId": dbus_to_native(group_id)}

    async def _list_groups(self, params: dict) -> list:
        groups = await self.signal_interface.call("listGroups", "", [])
        return [{"objectPath": str(g[0]), "groupId": dbus_to_native(g[1]), "name": str(g[2])} for g in groups]

    async def _get_group_members(self, params: dict) -> list:
        members = await self.signal_interface.call("getGroupMembers", "ay", [to_bytes(params["groupId"])])
        return list(members)

    async def _join_group(self, params: dict) -> None:
        await self.signal_interface.call("joinGroup", "s", [params["inviteURI"]])
        return None

    # -------------------------------------------------------------------------
    # Group sub-interface handlers
    # -------------------------------------------------------------------------

    async def _get_group_interface(self, group_id: str):
        """Get the org.asamk.Signal.Group interface for a groupId."""
        group_object_path = await self.signal_interface.call("getGroup", "ay", [to_bytes(group_id)])
        return self._client.sub_interface(str(group_object_path), "org.asamk.Signal.Group")

    async def _quit_group(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("quitGroup", "", [])
        return None

    async def _add_group_members(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("addMembers", "as", [params["recipients"]])
        return None

    async def _remove_group_members(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("removeMembers", "as", [params["recipients"]])
        return None

    async def _add_group_admins(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("addAdmins", "as", [params["recipients"]])
        return None

    async def _remove_group_admins(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("removeAdmins", "as", [params["recipients"]])
        return None

    async def _enable_group_link(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("enableLink", "b", [bool(params["requiresApproval"])])
        return None

    async def _disable_group_link(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("disableLink", "", [])
        return None

    async def _reset_group_link(self, params: dict) -> None:
        group_iface = await self._get_group_interface(params["groupId"])
        await group_iface.call("resetLink", "", [])
        return None

    # -------------------------------------------------------------------------
    # Contacts handlers
    # -------------------------------------------------------------------------

    async def _get_self_number(self, params: dict) -> dict:
        return {"number": str(await self.signal_interface.call("getSelfNumber", "", []))}

    async def _get_contact_name(self, params: dict) -> dict:
        return {"name": str(await self.signal_interface.call("getContactName", "s", [params["number"]]))}

    async def _get_contact_number(self, params: dict) -> dict:
        return {"numbers": list(await self.signal_interface.call("getContactNumber", "s", [params["name"]]))}

    async def _set_contact_name(self, params: dict) -> None:
        await self.signal_interface.call("setContactName", "ss", [params["number"], params["name"]])
        return None

    async def _is_contact_blocked(self, params: dict) -> dict:
        return {"blocked": bool(await self.signal_interface.call("isContactBlocked", "s", [params["number"]]))}

    async def _set_contact_blocked(self, params: dict) -> None:
        await self.signal_interface.call("setContactBlocked", "sb", [params["number"], bool(params["block"])])
        return None

    async def _delete_contact(self, params: dict) -> None:
        await self.signal_interface.call("deleteContact", "s", [params["number"]])
        return None

    async def _delete_recipient(self, params: dict) -> None:
        await self.signal_interface.call("deleteRecipient", "s", [params["number"]])
        return None

    async def _is_registered(self, params: dict) -> dict:
        if "numbers" in params:
            results = await self.signal_interface.call("isRegistered", "as", [params["numbers"]])
            return {"results": [bool(r) for r in results]}
        if "number" in params:
            return {"result": bool(await self.signal_interface.call("isRegistered", "s", [params["number"]]))}
        return {"result": bool(await self.signal_interface.call("isRegistered", "", []))}

    async def _list_numbers(self, params: dict) -> dict:
        return {"numbers": list(await self.signal_interface.call("listNumbers", "", []))}

    async def _set_expiration_timer(self, params: dict) -> None:
        await self.signal_interface.call("setExpirationTimer", "si", [params["number"], int(params["expiration"])])
        return None

    # -------------------------------------------------------------------------
    # Profile handlers
    # -------------------------------------------------------------------------

    async def _update_profile(self, params: dict) -> None:
        # updateProfile is overloaded in signal-cli: a 5-arg "name" form and a
        # 6-arg "givenName" form; pick the variant matching the params.
        if "givenName" in params:
            await self.signal_interface.call(
                "updateProfile",
                "sssssb",
                [
                    params["givenName"],
                    params.get("familyName", ""),
                    params.get("about", ""),
                    params.get("aboutEmoji", ""),
                    params.get("avatar", ""),
                    bool(params.get("remove", False)),
                ],
            )
        else:
            await self.signal_interface.call(
                "updateProfile",
                "ssssb",
                [
                    params["name"],
                    params.get("about", ""),
                    params.get("aboutEmoji", ""),
                    params.get("avatar", ""),
                    bool(params.get("remove", False)),
                ],
            )
        return None

    # -------------------------------------------------------------------------
    # Devices handlers
    # -------------------------------------------------------------------------

    async def _add_device(self, params: dict) -> None:
        await self.signal_interface.call("addDevice", "s", [params["deviceUri"]])
        return None

    async def _list_devices(self, params: dict) -> list:
        devices = await self.signal_interface.call("listDevices", "", [])
        return [{"objectPath": str(d[0]), "id": int(d[1]), "name": str(d[2])} for d in devices]

    async def _send_contacts(self, params: dict) -> None:
        await self.signal_interface.call("sendContacts", "", [])
        return None

    async def _send_sync_request(self, params: dict) -> None:
        await self.signal_interface.call("sendSyncRequest", "", [])
        return None

    # -------------------------------------------------------------------------
    # Misc handlers
    # -------------------------------------------------------------------------

    async def _version(self, params: dict) -> dict:
        return {"version": str(await self.signal_interface.call("version", "", []))}

    async def _submit_rate_limit(self, params: dict) -> None:
        await self.signal_interface.call("submitRateLimitChallenge", "ss", [params["challenge"], params["captcha"]])
        return None

    async def _upload_sticker_pack(self, params: dict) -> dict:
        url = await self.signal_interface.call("uploadStickerPack", "s", [params["stickerPackPath"]])
        return {"url": str(url)}

    # -------------------------------------------------------------------------
    # Identity handlers
    # -------------------------------------------------------------------------

    async def _list_identities(self, params: dict) -> list:
        identities = await self.signal_interface.call("listIdentities", "", [])
        return [{"objectPath": str(i[0]), "uuid": str(i[1]), "number": str(i[2])} for i in identities]

    async def _get_identity_interface(self, number: str):
        """Get the org.asamk.Signal.Identity interface for a phone number."""
        identity_object_path = await self.signal_interface.call("getIdentity", "s", [number])
        return self._client.sub_interface(str(identity_object_path), "org.asamk.Signal.Identity")

    async def _trust_identity(self, params: dict) -> None:
        identity_iface = await self._get_identity_interface(params["number"])
        await identity_iface.call("trust", "", [])
        return None

    async def _trust_identity_verified(self, params: dict) -> None:
        identity_iface = await self._get_identity_interface(params["number"])
        await identity_iface.call("trustVerified", "s", [params["safetyNumber"]])
        return None
