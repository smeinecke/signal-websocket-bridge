"""Tests for swb.dispatch module."""

from unittest.mock import MagicMock, patch

import pytest

dbus = pytest.importorskip("dbus")

from swb.dispatch import Method, MethodDispatcher


class TestMethodEnum:
    """Test Method enum values."""

    def test_method_values(self):
        """Test that all methods have correct string values."""
        assert Method.SEND_MESSAGE.value == "sendMessage"
        assert Method.SEND_GROUP_MESSAGE.value == "sendGroupMessage"
        assert Method.GET_SELF_NUMBER.value == "getSelfNumber"
        assert Method.VERSION.value == "version"
        assert Method.LIST_IDENTITIES.value == "listIdentities"


@pytest.fixture
def mock_interface():
    """Create a mock signal-cli interface."""
    return MagicMock()


@pytest.fixture
def mock_bus():
    """Create a mock DBus bus."""
    return MagicMock()


@pytest.fixture
def dispatcher(mock_interface, mock_bus):
    """Create a MethodDispatcher with mocked dependencies."""
    return MethodDispatcher(lambda: mock_interface, lambda: mock_bus)


class TestMessagingHandlers:
    """Test messaging method handlers."""

    def test_send_message(self, dispatcher, mock_interface):
        """Test sendMessage handler."""
        mock_interface.sendMessage.return_value = dbus.Int64(1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = dispatcher.dispatch(
                "sendMessage",
                {
                    "message": "Hello",
                    "recipients": ["+491234567890"],
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}
        mock_interface.sendMessage.assert_called_once_with("Hello", [], ["+491234567890"])

    def test_send_note_to_self(self, dispatcher, mock_interface):
        """Test sendNoteToSelfMessage handler."""
        mock_interface.sendNoteToSelfMessage.return_value = dbus.Int64(1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = dispatcher.dispatch(
                "sendNoteToSelfMessage",
                {
                    "message": "Note to self",
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}

    def test_send_message_reaction(self, dispatcher, mock_interface):
        """Test sendMessageReaction handler."""
        mock_interface.sendMessageReaction.return_value = dbus.Int64(1234567890123)

        result = dispatcher.dispatch(
            "sendMessageReaction",
            {
                "emoji": "👍",
                "remove": False,
                "targetAuthor": "+491234567890",
                "targetSentTimestamp": 1234567890000,
                "recipients": ["+491234567890"],
            },
        )

        assert result == {"timestamp": 1234567890123}

    def test_send_read_receipt(self, dispatcher, mock_interface):
        """Test sendReadReceipt handler."""
        result = dispatcher.dispatch(
            "sendReadReceipt",
            {
                "recipient": "+491234567890",
                "targetSentTimestamps": [1234567890000, 1234567890001],
            },
        )

        assert result is None
        mock_interface.sendReadReceipt.assert_called_once()


class TestGroupHandlers:
    """Test group method handlers."""

    def test_send_group_message(self, dispatcher, mock_interface):
        """Test sendGroupMessage handler."""
        mock_interface.sendGroupMessage.return_value = dbus.Int64(1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = dispatcher.dispatch(
                "sendGroupMessage",
                {
                    "message": "Group hello",
                    "groupId": "Z3JvdXAxMjM=",  # base64 of "group123"
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}

    def test_create_group(self, dispatcher, mock_interface):
        """Test createGroup handler."""
        mock_interface.createGroup.return_value = dbus.Array([dbus.Byte(b) for b in b"newgroup123"], signature="y")

        result = dispatcher.dispatch(
            "createGroup",
            {
                "groupName": "Test Group",
                "members": ["+491234567890"],
            },
        )

        assert "groupId" in result
        mock_interface.createGroup.assert_called_once_with("Test Group", ["+491234567890"], "")

    def test_list_groups(self, dispatcher, mock_interface):
        """Test listGroups handler."""
        mock_interface.listGroups.return_value = [
            dbus.Struct([
                dbus.ObjectPath("/org/asamk/Signal/Groups/group1"),
                dbus.Array([dbus.Byte(b) for b in b"group1"], signature="y"),
                dbus.String("Group One"),
            ]),
        ]

        result = dispatcher.dispatch("listGroups", {})

        assert len(result) == 1
        assert result[0]["name"] == "Group One"

    def test_get_group_members(self, dispatcher, mock_interface):
        """Test getGroupMembers handler."""
        mock_interface.getGroupMembers.return_value = ["+491234567890", "+499876543210"]

        result = dispatcher.dispatch(
            "getGroupMembers",
            {
                "groupId": "Z3JvdXAxMjM=",
            },
        )

        assert result == ["+491234567890", "+499876543210"]


class TestContactHandlers:
    """Test contact method handlers."""

    def test_get_self_number(self, dispatcher, mock_interface):
        """Test getSelfNumber handler."""
        mock_interface.getSelfNumber.return_value = dbus.String("+491234567890")

        result = dispatcher.dispatch("getSelfNumber", {})

        assert result == {"number": "+491234567890"}

    def test_get_contact_name(self, dispatcher, mock_interface):
        """Test getContactName handler."""
        mock_interface.getContactName.return_value = dbus.String("John Doe")

        result = dispatcher.dispatch(
            "getContactName",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"name": "John Doe"}

    def test_is_contact_blocked(self, dispatcher, mock_interface):
        """Test isContactBlocked handler."""
        mock_interface.isContactBlocked.return_value = dbus.Boolean(True)

        result = dispatcher.dispatch(
            "isContactBlocked",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"blocked": True}

    def test_set_contact_blocked(self, dispatcher, mock_interface):
        """Test setContactBlocked handler."""
        result = dispatcher.dispatch(
            "setContactBlocked",
            {
                "number": "+491234567890",
                "block": True,
            },
        )

        assert result is None
        mock_interface.setContactBlocked.assert_called_once_with("+491234567890", True)

    def test_is_registered_single(self, dispatcher, mock_interface):
        """Test isRegistered with single number."""
        mock_interface.isRegistered.return_value = dbus.Boolean(True)

        result = dispatcher.dispatch(
            "isRegistered",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"result": True}

    def test_is_registered_multiple(self, dispatcher, mock_interface):
        """Test isRegistered with multiple numbers."""
        mock_interface.isRegistered.return_value = [dbus.Boolean(True), dbus.Boolean(False)]

        result = dispatcher.dispatch(
            "isRegistered",
            {
                "numbers": ["+491234567890", "+499876543210"],
            },
        )

        assert result == {"results": [True, False]}


class TestProfileHandlers:
    """Test profile method handlers."""

    def test_update_profile_given_name(self, dispatcher, mock_interface):
        """Test updateProfile with givenName."""
        result = dispatcher.dispatch(
            "updateProfile",
            {
                "givenName": "John",
                "familyName": "Doe",
                "about": "Hello",
                "aboutEmoji": "👋",
                "avatar": "/path/avatar.png",
                "remove": False,
            },
        )

        assert result is None
        mock_interface.updateProfile.assert_called_once_with("John", "Doe", "Hello", "👋", "/path/avatar.png", False)

    def test_update_profile_simple(self, dispatcher, mock_interface):
        """Test updateProfile with simple name."""
        result = dispatcher.dispatch(
            "updateProfile",
            {
                "name": "John Doe",
                "about": "Hello",
            },
        )

        assert result is None
        mock_interface.updateProfile.assert_called_once_with("John Doe", "Hello", "", "", False)


class TestDeviceHandlers:
    """Test device method handlers."""

    def test_add_device(self, dispatcher, mock_interface):
        """Test addDevice handler."""
        result = dispatcher.dispatch(
            "addDevice",
            {
                "deviceUri": "sgnl://linkdevice?uuid=abc123",
            },
        )

        assert result is None
        mock_interface.addDevice.assert_called_once_with("sgnl://linkdevice?uuid=abc123")

    def test_list_devices(self, dispatcher, mock_interface):
        """Test listDevices handler."""
        mock_interface.listDevices.return_value = [
            dbus.Struct([
                dbus.ObjectPath("/org/asamk/Signal/Devices/1"),
                dbus.UInt32(1),
                dbus.String("Phone"),
            ]),
        ]

        result = dispatcher.dispatch("listDevices", {})

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Phone"


class TestMiscHandlers:
    """Test miscellaneous method handlers."""

    def test_version(self, dispatcher, mock_interface):
        """Test version handler."""
        mock_interface.version.return_value = dbus.String("0.12.0")

        result = dispatcher.dispatch("version", {})

        assert result == {"version": "0.12.0"}

    def test_submit_rate_limit_challenge(self, dispatcher, mock_interface):
        """Test submitRateLimitChallenge handler."""
        result = dispatcher.dispatch(
            "submitRateLimitChallenge",
            {
                "challenge": "challenge-token",
                "captcha": "captcha-response",
            },
        )

        assert result is None
        mock_interface.submitRateLimitChallenge.assert_called_once_with("challenge-token", "captcha-response")

    def test_upload_sticker_pack(self, dispatcher, mock_interface):
        """Test uploadStickerPack handler."""
        mock_interface.uploadStickerPack.return_value = dbus.String("https://signal.art/addstickers/?pack=abc123")

        result = dispatcher.dispatch(
            "uploadStickerPack",
            {
                "stickerPackPath": "/path/to/stickers",
            },
        )

        assert result == {"url": "https://signal.art/addstickers/?pack=abc123"}


class TestErrorHandling:
    """Test error handling."""

    def test_unknown_method(self, dispatcher):
        """Test unknown method raises ValueError."""
        with pytest.raises(ValueError, match="unknown method"):
            dispatcher.dispatch("unknownMethod", {})

    def test_missing_params(self, dispatcher):
        """Test missing required params raises KeyError."""
        with pytest.raises((KeyError, TypeError)):
            dispatcher.dispatch("sendMessage", {})  # Missing required params


class TestGroupSubInterfaceHandlers:
    """Test group sub-interface method handlers."""

    def test_quit_group(self, dispatcher, mock_interface, mock_bus):
        """Test quitGroup handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "quitGroup",
                {"groupId": "Z3JvdXAxMjM="},
            )

        assert result is None
        mock_group_iface.quitGroup.assert_called_once()

    def test_add_group_members(self, dispatcher, mock_interface, mock_bus):
        """Test addGroupMembers handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "addGroupMembers",
                {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
            )

        assert result is None
        mock_group_iface.addMembers.assert_called_once_with(["+491234567890"])

    def test_remove_group_members(self, dispatcher, mock_interface, mock_bus):
        """Test removeGroupMembers handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "removeGroupMembers",
                {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
            )

        assert result is None
        mock_group_iface.removeMembers.assert_called_once_with(["+491234567890"])

    def test_add_group_admins(self, dispatcher, mock_interface, mock_bus):
        """Test addGroupAdmins handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "addGroupAdmins",
                {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
            )

        assert result is None
        mock_group_iface.addAdmins.assert_called_once_with(["+491234567890"])

    def test_remove_group_admins(self, dispatcher, mock_interface, mock_bus):
        """Test removeGroupAdmins handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "removeGroupAdmins",
                {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
            )

        assert result is None
        mock_group_iface.removeAdmins.assert_called_once_with(["+491234567890"])

    def test_enable_group_link(self, dispatcher, mock_interface, mock_bus):
        """Test enableGroupLink handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "enableGroupLink",
                {"groupId": "Z3JvdXAxMjM=", "requiresApproval": True},
            )

        assert result is None
        mock_group_iface.enableLink.assert_called_once_with(True)

    def test_disable_group_link(self, dispatcher, mock_interface, mock_bus):
        """Test disableGroupLink handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "disableGroupLink",
                {"groupId": "Z3JvdXAxMjM="},
            )

        assert result is None
        mock_group_iface.disableLink.assert_called_once()

    def test_reset_group_link(self, dispatcher, mock_interface, mock_bus):
        """Test resetGroupLink handler."""
        mock_group_iface = MagicMock()
        mock_interface.getGroup.return_value = "/org/asamk/Signal/Groups/group1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_group_iface):
            result = dispatcher.dispatch(
                "resetGroupLink",
                {"groupId": "Z3JvdXAxMjM="},
            )

        assert result is None
        mock_group_iface.resetLink.assert_called_once()


class TestMoreContactHandlers:
    """Additional contact handler tests."""

    def test_get_contact_number(self, dispatcher, mock_interface):
        """Test getContactNumber handler."""
        mock_interface.getContactNumber.return_value = dbus.Array([dbus.String("+491234567890")])

        result = dispatcher.dispatch(
            "getContactNumber",
            {"name": "John Doe"},
        )

        assert result == {"numbers": ["+491234567890"]}

    def test_set_contact_name(self, dispatcher, mock_interface):
        """Test setContactName handler."""
        result = dispatcher.dispatch(
            "setContactName",
            {"number": "+491234567890", "name": "John Doe"},
        )

        assert result is None
        mock_interface.setContactName.assert_called_once_with("+491234567890", "John Doe")

    def test_delete_contact(self, dispatcher, mock_interface):
        """Test deleteContact handler."""
        result = dispatcher.dispatch(
            "deleteContact",
            {"number": "+491234567890"},
        )

        assert result is None
        mock_interface.deleteContact.assert_called_once_with("+491234567890")

    def test_delete_recipient(self, dispatcher, mock_interface):
        """Test deleteRecipient handler."""
        result = dispatcher.dispatch(
            "deleteRecipient",
            {"number": "+491234567890"},
        )

        assert result is None
        mock_interface.deleteRecipient.assert_called_once_with("+491234567890")

    def test_list_numbers(self, dispatcher, mock_interface):
        """Test listNumbers handler."""
        mock_interface.listNumbers.return_value = dbus.Array([dbus.String("+491234567890")])

        result = dispatcher.dispatch("listNumbers", {})

        assert result == {"numbers": ["+491234567890"]}

    def test_set_expiration_timer(self, dispatcher, mock_interface):
        """Test setExpirationTimer handler."""
        result = dispatcher.dispatch(
            "setExpirationTimer",
            {"number": "+491234567890", "expiration": 86400},
        )

        assert result is None
        mock_interface.setExpirationTimer.assert_called_once()


class TestMoreMessagingHandlers:
    """Additional messaging handler tests."""

    def test_send_viewed_receipt(self, dispatcher, mock_interface):
        """Test sendViewedReceipt handler."""
        result = dispatcher.dispatch(
            "sendViewedReceipt",
            {
                "recipient": "+491234567890",
                "targetSentTimestamps": [1234567890000],
            },
        )

        assert result is None
        mock_interface.sendViewedReceipt.assert_called_once()

    def test_send_typing_start(self, dispatcher, mock_interface):
        """Test sendTyping with start."""
        result = dispatcher.dispatch(
            "sendTyping",
            {"recipient": "+491234567890", "stop": False},
        )

        assert result is None
        mock_interface.sendTyping.assert_called_once_with("+491234567890", False)

    def test_send_typing_stop(self, dispatcher, mock_interface):
        """Test sendTyping with stop."""
        result = dispatcher.dispatch(
            "sendTyping",
            {"recipient": "+491234567890", "stop": True},
        )

        assert result is None
        mock_interface.sendTyping.assert_called_once_with("+491234567890", True)

    def test_send_end_session(self, dispatcher, mock_interface):
        """Test sendEndSessionMessage handler."""
        result = dispatcher.dispatch(
            "sendEndSessionMessage",
            {"recipients": ["+491234567890"]},
        )

        assert result is None
        mock_interface.sendEndSessionMessage.assert_called_once_with(["+491234567890"])

    def test_send_payment_notification(self, dispatcher, mock_interface):
        """Test sendPaymentNotification handler."""
        mock_interface.sendPaymentNotification.return_value = dbus.Int64(1234567890123)

        result = dispatcher.dispatch(
            "sendPaymentNotification",
            {
                "receipt": "cmVjZWlwdA==",  # base64 of "receipt"
                "note": "Payment note",
                "recipient": "+491234567890",
            },
        )

        assert result == {"timestamp": 1234567890123}

    def test_send_remote_delete(self, dispatcher, mock_interface):
        """Test sendRemoteDeleteMessage handler."""
        mock_interface.sendRemoteDeleteMessage.return_value = dbus.Int64(1234567890123)

        result = dispatcher.dispatch(
            "sendRemoteDeleteMessage",
            {
                "targetSentTimestamp": 1234567890000,
                "recipients": ["+491234567890"],
            },
        )

        assert result == {"timestamp": 1234567890123}


class TestIdentityHandlers:
    """Test identity method handlers."""

    def test_list_identities(self, dispatcher, mock_interface):
        """Test listIdentities handler."""
        mock_interface.listIdentities.return_value = [
            dbus.Struct([
                dbus.ObjectPath("/org/asamk/Signal/Identities/1"),
                dbus.String("uuid-123"),
                dbus.String("+491234567890"),
            ]),
        ]

        result = dispatcher.dispatch("listIdentities", {})

        assert len(result) == 1
        assert result[0]["uuid"] == "uuid-123"

    def test_trust_identity(self, dispatcher, mock_interface, mock_bus):
        """Test trustIdentity handler."""
        mock_identity_iface = MagicMock()
        mock_interface.getIdentity.return_value = "/org/asamk/Signal/Identities/1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_identity_iface):
            result = dispatcher.dispatch(
                "trustIdentity",
                {"number": "+491234567890"},
            )

        assert result is None
        mock_identity_iface.trust.assert_called_once()

    def test_trust_identity_verified(self, dispatcher, mock_interface, mock_bus):
        """Test trustIdentityVerified handler."""
        mock_identity_iface = MagicMock()
        mock_interface.getIdentity.return_value = "/org/asamk/Signal/Identities/1"

        with patch("swb.dispatch.dbus.Interface", return_value=mock_identity_iface):
            result = dispatcher.dispatch(
                "trustIdentityVerified",
                {"number": "+491234567890", "safetyNumber": "12345678901234567890"},
            )

        assert result is None
        mock_identity_iface.trustVerified.assert_called_once_with("12345678901234567890")


class TestMoreDeviceHandlers:
    """Additional device handler tests."""

    def test_send_contacts(self, dispatcher, mock_interface):
        """Test sendContacts handler."""
        result = dispatcher.dispatch("sendContacts", {})

        assert result is None
        mock_interface.sendContacts.assert_called_once()

    def test_send_sync_request(self, dispatcher, mock_interface):
        """Test sendSyncRequest handler."""
        result = dispatcher.dispatch("sendSyncRequest", {})

        assert result is None
        mock_interface.sendSyncRequest.assert_called_once()


class TestMoreGroupHandlers:
    """Additional group handler tests."""

    def test_send_group_message_reaction(self, dispatcher, mock_interface):
        """Test sendGroupMessageReaction handler."""
        mock_interface.sendGroupMessageReaction.return_value = dbus.Int64(1234567890123)

        result = dispatcher.dispatch(
            "sendGroupMessageReaction",
            {
                "emoji": "👍",
                "remove": False,
                "targetAuthor": "+491234567890",
                "targetSentTimestamp": 1234567890000,
                "groupId": "Z3JvdXAxMjM=",
            },
        )

        assert result == {"timestamp": 1234567890123}

    def test_send_group_remote_delete(self, dispatcher, mock_interface):
        """Test sendGroupRemoteDeleteMessage handler."""
        mock_interface.sendGroupRemoteDeleteMessage.return_value = dbus.Int64(1234567890123)

        result = dispatcher.dispatch(
            "sendGroupRemoteDeleteMessage",
            {
                "targetSentTimestamp": 1234567890000,
                "groupId": "Z3JvdXAxMjM=",
            },
        )

        assert result == {"timestamp": 1234567890123}

    def test_send_group_typing(self, dispatcher, mock_interface):
        """Test sendGroupTyping handler."""
        result = dispatcher.dispatch(
            "sendGroupTyping",
            {"groupId": "Z3JvdXAxMjM=", "stop": True},
        )

        assert result is None
        mock_interface.sendGroupTyping.assert_called_once()

    def test_join_group(self, dispatcher, mock_interface):
        """Test joinGroup handler."""
        result = dispatcher.dispatch(
            "joinGroup",
            {"inviteURI": "sgnl://linkdevice?uuid=abc123"},
        )

        assert result is None
        mock_interface.joinGroup.assert_called_once_with("sgnl://linkdevice?uuid=abc123")


class TestIsRegisteredNoParams:
    """Test isRegistered with no parameters."""

    def test_is_registered_no_params(self, dispatcher, mock_interface):
        """Test isRegistered with no params at all."""
        mock_interface.isRegistered.return_value = dbus.Boolean(True)

        result = dispatcher.dispatch("isRegistered", {})

        assert result == {"result": True}
        mock_interface.isRegistered.assert_called_once_with()


class TestDispatchHandlerNotFound:
    """Test dispatch when handler is not found."""

    def test_dispatch_handler_not_found(self, dispatcher):
        """Test dispatch raises when handler is None."""
        # This tests line 157 - when handler is None after getting from _handlers
        # We need to mock _handlers to return None for a valid method enum
        from unittest.mock import patch

        with patch.object(dispatcher, "_handlers", {}):
            with pytest.raises(ValueError, match="no handler for method"):
                dispatcher.dispatch("sendMessage", {"message": "test", "recipients": ["+123"]})
