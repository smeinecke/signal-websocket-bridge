"""Method dispatching from WebSocket JSON-RPC to DBus calls."""

from enum import Enum
from typing import Callable

import dbus

from swb.types import (
    dbus_to_native,
    to_bytes,
    to_int64,
    to_int64_array,
    to_string_array,
    validate_attachments,
)


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

    Uses callable getters for the interface and bus so that reconnections
    are transparent — stale references are never held across a disconnect.
    """

    def __init__(self, get_interface, get_bus):
        """
        Args:
            get_interface: zero-argument callable returning the current dbus.Interface
            get_bus:       zero-argument callable returning the current dbus.Bus
        """
        self._get_interface = get_interface
        self._get_bus = get_bus
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
    def signal_interface(self):
        return self._get_interface()

    @property
    def bus(self):
        return self._get_bus()

    def dispatch(self, method_name: str, params: dict):
        """Dispatch JSON-RPC method call to appropriate handler."""
        try:
            method = Method(method_name)
        except ValueError:
            raise ValueError(f"unknown method '{method_name}'")

        handler = self._handlers.get(method)
        if not handler:
            raise ValueError(f"no handler for method '{method_name}'")

        return handler(params)

    # -------------------------------------------------------------------------
    # Messaging handlers
    # -------------------------------------------------------------------------

    def _send_message(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = self.signal_interface.sendMessage(
            params["message"],
            to_string_array(attachments),
            params["recipients"],
        )
        return {"timestamp": int(ts)}

    def _send_note_to_self(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = self.signal_interface.sendNoteToSelfMessage(params["message"], to_string_array(attachments))
        return {"timestamp": int(ts)}

    def _send_message_reaction(self, params: dict) -> dict:
        ts = self.signal_interface.sendMessageReaction(
            params["emoji"],
            bool(params["remove"]),
            params["targetAuthor"],
            to_int64(params["targetSentTimestamp"]),
            params["recipients"],
        )
        return {"timestamp": int(ts)}

    def _send_read_receipt(self, params: dict) -> None:
        self.signal_interface.sendReadReceipt(
            params["recipient"],
            to_int64_array(params["targetSentTimestamps"]),
        )
        return None

    def _send_viewed_receipt(self, params: dict) -> None:
        self.signal_interface.sendViewedReceipt(
            params["recipient"],
            to_int64_array(params["targetSentTimestamps"]),
        )
        return None

    def _send_typing(self, params: dict) -> None:
        self.signal_interface.sendTyping(params["recipient"], bool(params.get("stop", False)))
        return None

    def _send_remote_delete(self, params: dict) -> dict:
        ts = self.signal_interface.sendRemoteDeleteMessage(
            to_int64(params["targetSentTimestamp"]),
            params["recipients"],
        )
        return {"timestamp": int(ts)}

    def _send_end_session(self, params: dict) -> None:
        self.signal_interface.sendEndSessionMessage(params["recipients"])
        return None

    def _send_payment_notification(self, params: dict) -> dict:
        ts = self.signal_interface.sendPaymentNotification(
            to_bytes(params["receipt"]),
            params["note"],
            params["recipient"],
        )
        return {"timestamp": int(ts)}

    # -------------------------------------------------------------------------
    # Groups (main interface) handlers
    # -------------------------------------------------------------------------

    def _send_group_message(self, params: dict) -> dict:
        attachments = params.get("attachments", [])
        validate_attachments(attachments)
        ts = self.signal_interface.sendGroupMessage(
            params["message"],
            to_string_array(attachments),
            to_bytes(params["groupId"]),
        )
        return {"timestamp": int(ts)}

    def _send_group_message_reaction(self, params: dict) -> dict:
        ts = self.signal_interface.sendGroupMessageReaction(
            params["emoji"],
            bool(params["remove"]),
            params["targetAuthor"],
            to_int64(params["targetSentTimestamp"]),
            to_bytes(params["groupId"]),
        )
        return {"timestamp": int(ts)}

    def _send_group_remote_delete(self, params: dict) -> dict:
        ts = self.signal_interface.sendGroupRemoteDeleteMessage(
            to_int64(params["targetSentTimestamp"]),
            to_bytes(params["groupId"]),
        )
        return {"timestamp": int(ts)}

    def _send_group_typing(self, params: dict) -> None:
        self.signal_interface.sendGroupTyping(
            to_bytes(params["groupId"]),
            bool(params.get("stop", False)),
        )
        return None

    def _create_group(self, params: dict) -> dict:
        group_id = self.signal_interface.createGroup(
            params["groupName"],
            params.get("members", []),
            params.get("avatar", ""),
        )
        return {"groupId": dbus_to_native(group_id)}

    def _list_groups(self, params: dict) -> list:
        groups = self.signal_interface.listGroups()
        return [{"objectPath": str(g[0]), "groupId": dbus_to_native(g[1]), "name": str(g[2])} for g in groups]

    def _get_group_members(self, params: dict) -> list:
        members = self.signal_interface.getGroupMembers(to_bytes(params["groupId"]))
        return list(members)

    def _join_group(self, params: dict) -> None:
        self.signal_interface.joinGroup(params["inviteURI"])
        return None

    # -------------------------------------------------------------------------
    # Group sub-interface handlers
    # -------------------------------------------------------------------------

    def _get_group_interface(self, group_id: str):
        """Get the org.asamk.Signal.Group interface for a groupId."""
        group_id_bytes = to_bytes(group_id)
        group_object_path = self.signal_interface.getGroup(group_id_bytes)
        group_obj = self.bus.get_object("org.asamk.Signal", group_object_path)
        return dbus.Interface(group_obj, "org.asamk.Signal.Group")

    def _quit_group(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.quitGroup()
        return None

    def _add_group_members(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.addMembers(params["recipients"])
        return None

    def _remove_group_members(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.removeMembers(params["recipients"])
        return None

    def _add_group_admins(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.addAdmins(params["recipients"])
        return None

    def _remove_group_admins(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.removeAdmins(params["recipients"])
        return None

    def _enable_group_link(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.enableLink(bool(params["requiresApproval"]))
        return None

    def _disable_group_link(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.disableLink()
        return None

    def _reset_group_link(self, params: dict) -> None:
        group_iface = self._get_group_interface(params["groupId"])
        group_iface.resetLink()
        return None

    # -------------------------------------------------------------------------
    # Contacts handlers
    # -------------------------------------------------------------------------

    def _get_self_number(self, params: dict) -> dict:
        return {"number": str(self.signal_interface.getSelfNumber())}

    def _get_contact_name(self, params: dict) -> dict:
        return {"name": str(self.signal_interface.getContactName(params["number"]))}

    def _get_contact_number(self, params: dict) -> dict:
        return {"numbers": list(self.signal_interface.getContactNumber(params["name"]))}

    def _set_contact_name(self, params: dict) -> None:
        self.signal_interface.setContactName(params["number"], params["name"])
        return None

    def _is_contact_blocked(self, params: dict) -> dict:
        return {"blocked": bool(self.signal_interface.isContactBlocked(params["number"]))}

    def _set_contact_blocked(self, params: dict) -> None:
        self.signal_interface.setContactBlocked(params["number"], bool(params["block"]))
        return None

    def _delete_contact(self, params: dict) -> None:
        self.signal_interface.deleteContact(params["number"])
        return None

    def _delete_recipient(self, params: dict) -> None:
        self.signal_interface.deleteRecipient(params["number"])
        return None

    def _is_registered(self, params: dict) -> dict:
        if "numbers" in params:
            results = self.signal_interface.isRegistered(params["numbers"])
            return {"results": [bool(r) for r in results]}
        if "number" in params:
            return {"result": bool(self.signal_interface.isRegistered(params["number"]))}
        return {"result": bool(self.signal_interface.isRegistered())}

    def _list_numbers(self, params: dict) -> dict:
        return {"numbers": list(self.signal_interface.listNumbers())}

    def _set_expiration_timer(self, params: dict) -> None:
        self.signal_interface.setExpirationTimer(params["number"], dbus.Int32(int(params["expiration"])))
        return None

    # -------------------------------------------------------------------------
    # Profile handlers
    # -------------------------------------------------------------------------

    def _update_profile(self, params: dict) -> None:
        if "givenName" in params:
            self.signal_interface.updateProfile(
                params["givenName"],
                params.get("familyName", ""),
                params.get("about", ""),
                params.get("aboutEmoji", ""),
                params.get("avatar", ""),
                bool(params.get("remove", False)),
            )
        else:
            self.signal_interface.updateProfile(
                params["name"],
                params.get("about", ""),
                params.get("aboutEmoji", ""),
                params.get("avatar", ""),
                bool(params.get("remove", False)),
            )
        return None

    # -------------------------------------------------------------------------
    # Devices handlers
    # -------------------------------------------------------------------------

    def _add_device(self, params: dict) -> None:
        self.signal_interface.addDevice(params["deviceUri"])
        return None

    def _list_devices(self, params: dict) -> list:
        devices = self.signal_interface.listDevices()
        return [{"objectPath": str(d[0]), "id": int(d[1]), "name": str(d[2])} for d in devices]

    def _send_contacts(self, params: dict) -> None:
        self.signal_interface.sendContacts()
        return None

    def _send_sync_request(self, params: dict) -> None:
        self.signal_interface.sendSyncRequest()
        return None

    # -------------------------------------------------------------------------
    # Misc handlers
    # -------------------------------------------------------------------------

    def _version(self, params: dict) -> dict:
        return {"version": str(self.signal_interface.version())}

    def _submit_rate_limit(self, params: dict) -> None:
        self.signal_interface.submitRateLimitChallenge(params["challenge"], params["captcha"])
        return None

    def _upload_sticker_pack(self, params: dict) -> dict:
        url = self.signal_interface.uploadStickerPack(params["stickerPackPath"])
        return {"url": str(url)}

    # -------------------------------------------------------------------------
    # Identity handlers
    # -------------------------------------------------------------------------

    def _list_identities(self, params: dict) -> list:
        identities = self.signal_interface.listIdentities()
        return [{"objectPath": str(i[0]), "uuid": str(i[1]), "number": str(i[2])} for i in identities]

    def _get_identity_interface(self, number: str):
        """Get the org.asamk.Signal.Identity interface for a phone number."""
        identity_object_path = self.signal_interface.getIdentity(number)
        identity_obj = self.bus.get_object("org.asamk.Signal", identity_object_path)
        return dbus.Interface(identity_obj, "org.asamk.Signal.Identity")

    def _trust_identity(self, params: dict) -> None:
        identity_iface = self._get_identity_interface(params["number"])
        identity_iface.trust()
        return None

    def _trust_identity_verified(self, params: dict) -> None:
        identity_iface = self._get_identity_interface(params["number"])
        identity_iface.trustVerified(params["safetyNumber"])
        return None
