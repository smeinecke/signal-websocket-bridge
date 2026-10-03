"""Tests for swb.dispatch module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    """Create a mock signal-cli proxy interface with async call_* methods."""
    return MagicMock()


@pytest.fixture
def mock_client(mock_interface):
    """Create a mock SignalClient."""
    client = MagicMock()
    client.interface = MagicMock(return_value=mock_interface)
    client.sub_interface = MagicMock()
    return client


@pytest.fixture
def dispatcher(mock_client):
    """Create a MethodDispatcher with a mocked client."""
    return MethodDispatcher(mock_client)


class TestMessagingHandlers:
    """Test messaging method handlers."""

    async def test_send_message(self, dispatcher, mock_interface):
        """Test sendMessage handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = await dispatcher.dispatch(
                "sendMessage",
                {
                    "message": "Hello",
                    "recipients": ["+491234567890"],
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}
        mock_interface.call.assert_called_once_with("sendMessage", "sasas", ["Hello", [], ["+491234567890"]])

    async def test_send_note_to_self(self, dispatcher, mock_interface):
        """Test sendNoteToSelfMessage handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = await dispatcher.dispatch(
                "sendNoteToSelfMessage",
                {
                    "message": "Note to self",
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}

    async def test_send_message_reaction(self, dispatcher, mock_interface):
        """Test sendMessageReaction handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        result = await dispatcher.dispatch(
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

    async def test_send_read_receipt(self, dispatcher, mock_interface):
        """Test sendReadReceipt handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "sendReadReceipt",
            {
                "recipient": "+491234567890",
                "targetSentTimestamps": [1234567890000, 1234567890001],
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("sendReadReceipt", "sax", ["+491234567890", [1234567890000, 1234567890001]])


class TestGroupHandlers:
    """Test group method handlers."""

    async def test_send_group_message(self, dispatcher, mock_interface):
        """Test sendGroupMessage handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        with patch("swb.dispatch.validate_attachments"):
            result = await dispatcher.dispatch(
                "sendGroupMessage",
                {
                    "message": "Group hello",
                    "groupId": "Z3JvdXAxMjM=",  # base64 of "group123"
                    "attachments": [],
                },
            )

        assert result == {"timestamp": 1234567890123}

    async def test_create_group(self, dispatcher, mock_interface):
        """Test createGroup handler."""
        mock_interface.call = AsyncMock(return_value=b"newgroup123")

        result = await dispatcher.dispatch(
            "createGroup",
            {
                "groupName": "Test Group",
                "members": ["+491234567890"],
            },
        )

        assert "groupId" in result
        mock_interface.call.assert_called_once_with("createGroup", "sass", ["Test Group", ["+491234567890"], ""])

    async def test_list_groups(self, dispatcher, mock_interface):
        """Test listGroups handler."""
        mock_interface.call = AsyncMock(
            return_value=[
                ["/org/asamk/Signal/Groups/group1", b"group1", "Group One"],
            ]
        )

        result = await dispatcher.dispatch("listGroups", {})

        assert len(result) == 1
        assert result[0]["name"] == "Group One"
        assert result[0]["groupId"] == "Z3JvdXAx"  # base64 of b"group1"

    async def test_get_group_members(self, dispatcher, mock_interface):
        """Test getGroupMembers handler."""
        mock_interface.call = AsyncMock(return_value=["+491234567890", "+499876543210"])

        result = await dispatcher.dispatch(
            "getGroupMembers",
            {
                "groupId": "Z3JvdXAxMjM=",
            },
        )

        assert result == ["+491234567890", "+499876543210"]


class TestContactHandlers:
    """Test contact method handlers."""

    async def test_get_self_number(self, dispatcher, mock_interface):
        """Test getSelfNumber handler."""
        mock_interface.call = AsyncMock(return_value="+491234567890")

        result = await dispatcher.dispatch("getSelfNumber", {})

        assert result == {"number": "+491234567890"}

    async def test_get_contact_name(self, dispatcher, mock_interface):
        """Test getContactName handler."""
        mock_interface.call = AsyncMock(return_value="John Doe")

        result = await dispatcher.dispatch(
            "getContactName",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"name": "John Doe"}

    async def test_is_contact_blocked(self, dispatcher, mock_interface):
        """Test isContactBlocked handler."""
        mock_interface.call = AsyncMock(return_value=True)

        result = await dispatcher.dispatch(
            "isContactBlocked",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"blocked": True}

    async def test_set_contact_blocked(self, dispatcher, mock_interface):
        """Test setContactBlocked handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "setContactBlocked",
            {
                "number": "+491234567890",
                "block": True,
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("setContactBlocked", "sb", ["+491234567890", True])

    async def test_is_registered_single(self, dispatcher, mock_interface):
        """Test isRegistered with single number."""
        mock_interface.call = AsyncMock(return_value=True)

        result = await dispatcher.dispatch(
            "isRegistered",
            {
                "number": "+491234567890",
            },
        )

        assert result == {"result": True}

    async def test_is_registered_multiple(self, dispatcher, mock_interface):
        """Test isRegistered with multiple numbers."""
        mock_interface.call = AsyncMock(return_value=[True, False])

        result = await dispatcher.dispatch(
            "isRegistered",
            {
                "numbers": ["+491234567890", "+499876543210"],
            },
        )

        assert result == {"results": [True, False]}


class TestProfileHandlers:
    """Test profile method handlers."""

    async def test_update_profile_given_name(self, dispatcher, mock_interface):
        """Test updateProfile with givenName."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
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
        mock_interface.call.assert_called_once_with("updateProfile", "sssssb", ["John", "Doe", "Hello", "👋", "/path/avatar.png", False])

    async def test_update_profile_simple(self, dispatcher, mock_interface):
        """Test updateProfile with simple name."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "updateProfile",
            {
                "name": "John Doe",
                "about": "Hello",
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("updateProfile", "ssssb", ["John Doe", "Hello", "", "", False])


class TestDeviceHandlers:
    """Test device method handlers."""

    async def test_add_device(self, dispatcher, mock_interface):
        """Test addDevice handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "addDevice",
            {
                "deviceUri": "sgnl://linkdevice?uuid=abc123",
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("addDevice", "s", ["sgnl://linkdevice?uuid=abc123"])

    async def test_list_devices(self, dispatcher, mock_interface):
        """Test listDevices handler."""
        mock_interface.call = AsyncMock(
            return_value=[
                ["/org/asamk/Signal/Devices/1", 1, "Phone"],
            ]
        )

        result = await dispatcher.dispatch("listDevices", {})

        assert len(result) == 1
        assert result[0]["id"] == 1
        assert result[0]["name"] == "Phone"


class TestMiscHandlers:
    """Test miscellaneous method handlers."""

    async def test_version(self, dispatcher, mock_interface):
        """Test version handler."""
        mock_interface.call = AsyncMock(return_value="0.12.0")

        result = await dispatcher.dispatch("version", {})

        assert result == {"version": "0.12.0"}

    async def test_submit_rate_limit_challenge(self, dispatcher, mock_interface):
        """Test submitRateLimitChallenge handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "submitRateLimitChallenge",
            {
                "challenge": "challenge-token",
                "captcha": "captcha-response",
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("submitRateLimitChallenge", "ss", ["challenge-token", "captcha-response"])

    async def test_upload_sticker_pack(self, dispatcher, mock_interface):
        """Test uploadStickerPack handler."""
        mock_interface.call = AsyncMock(return_value="https://signal.art/addstickers/?pack=abc123")

        result = await dispatcher.dispatch(
            "uploadStickerPack",
            {
                "stickerPackPath": "/path/to/stickers",
            },
        )

        assert result == {"url": "https://signal.art/addstickers/?pack=abc123"}


class TestErrorHandling:
    """Test error handling."""

    async def test_unknown_method(self, dispatcher):
        """Test unknown method raises ValueError."""
        with pytest.raises(ValueError, match="unknown method"):
            await dispatcher.dispatch("unknownMethod", {})

    async def test_missing_params(self, dispatcher, mock_interface):
        """Test missing required params raises KeyError."""
        mock_interface.call = AsyncMock()
        with pytest.raises((KeyError, TypeError)):
            await dispatcher.dispatch("sendMessage", {})  # Missing required params


class TestGroupSubInterfaceHandlers:
    """Test group sub-interface method handlers."""

    async def _run_group_call(self, dispatcher, mock_client, mock_interface, method, params):
        """Dispatch a group sub-interface call and return the sub-interface mock."""
        mock_group_iface = MagicMock()
        mock_group_iface.call = AsyncMock(return_value=None)
        mock_interface.call = AsyncMock(return_value="/org/asamk/Signal/Groups/group1")
        mock_client.sub_interface = MagicMock(return_value=mock_group_iface)

        result = await dispatcher.dispatch(method, params)
        assert result is None
        return mock_group_iface

    async def test_quit_group(self, dispatcher, mock_client, mock_interface):
        """Test quitGroup handler."""
        mock_group_iface = await self._run_group_call(dispatcher, mock_client, mock_interface, "quitGroup", {"groupId": "Z3JvdXAxMjM="})
        mock_group_iface.call.assert_called_once_with("quitGroup", "", [])

    async def test_add_group_members(self, dispatcher, mock_client, mock_interface):
        """Test addGroupMembers handler."""
        mock_group_iface = await self._run_group_call(
            dispatcher, mock_client, mock_interface, "addGroupMembers", {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]}
        )
        mock_group_iface.call.assert_called_once_with("addMembers", "as", [["+491234567890"]])

    async def test_remove_group_members(self, dispatcher, mock_client, mock_interface):
        """Test removeGroupMembers handler."""
        mock_group_iface = await self._run_group_call(
            dispatcher,
            mock_client,
            mock_interface,
            "removeGroupMembers",
            {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
        )
        mock_group_iface.call.assert_called_once_with("removeMembers", "as", [["+491234567890"]])

    async def test_add_group_admins(self, dispatcher, mock_client, mock_interface):
        """Test addGroupAdmins handler."""
        mock_group_iface = await self._run_group_call(
            dispatcher,
            mock_client,
            mock_interface,
            "addGroupAdmins",
            {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
        )
        mock_group_iface.call.assert_called_once_with("addAdmins", "as", [["+491234567890"]])

    async def test_remove_group_admins(self, dispatcher, mock_client, mock_interface):
        """Test removeGroupAdmins handler."""
        mock_group_iface = await self._run_group_call(
            dispatcher,
            mock_client,
            mock_interface,
            "removeGroupAdmins",
            {"groupId": "Z3JvdXAxMjM=", "recipients": ["+491234567890"]},
        )
        mock_group_iface.call.assert_called_once_with("removeAdmins", "as", [["+491234567890"]])

    async def test_enable_group_link(self, dispatcher, mock_client, mock_interface):
        """Test enableGroupLink handler."""
        mock_group_iface = await self._run_group_call(
            dispatcher, mock_client, mock_interface, "enableGroupLink", {"groupId": "Z3JvdXAxMjM=", "requiresApproval": True}
        )
        mock_group_iface.call.assert_called_once_with("enableLink", "b", [True])

    async def test_disable_group_link(self, dispatcher, mock_client, mock_interface):
        """Test disableGroupLink handler."""
        mock_group_iface = await self._run_group_call(dispatcher, mock_client, mock_interface, "disableGroupLink", {"groupId": "Z3JvdXAxMjM="})
        mock_group_iface.call.assert_called_once_with("disableLink", "", [])

    async def test_reset_group_link(self, dispatcher, mock_client, mock_interface):
        """Test resetGroupLink handler."""
        mock_group_iface = await self._run_group_call(dispatcher, mock_client, mock_interface, "resetGroupLink", {"groupId": "Z3JvdXAxMjM="})
        mock_group_iface.call.assert_called_once_with("resetLink", "", [])


class TestMoreContactHandlers:
    """Additional contact handler tests."""

    async def test_get_contact_number(self, dispatcher, mock_interface):
        """Test getContactNumber handler."""
        mock_interface.call = AsyncMock(return_value=["+491234567890"])

        result = await dispatcher.dispatch(
            "getContactNumber",
            {"name": "John Doe"},
        )

        assert result == {"numbers": ["+491234567890"]}

    async def test_set_contact_name(self, dispatcher, mock_interface):
        """Test setContactName handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "setContactName",
            {"number": "+491234567890", "name": "John Doe"},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("setContactName", "ss", ["+491234567890", "John Doe"])

    async def test_delete_contact(self, dispatcher, mock_interface):
        """Test deleteContact handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "deleteContact",
            {"number": "+491234567890"},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("deleteContact", "s", ["+491234567890"])

    async def test_delete_recipient(self, dispatcher, mock_interface):
        """Test deleteRecipient handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "deleteRecipient",
            {"number": "+491234567890"},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("deleteRecipient", "s", ["+491234567890"])

    async def test_list_numbers(self, dispatcher, mock_interface):
        """Test listNumbers handler."""
        mock_interface.call = AsyncMock(return_value=["+491234567890"])

        result = await dispatcher.dispatch("listNumbers", {})

        assert result == {"numbers": ["+491234567890"]}

    async def test_set_expiration_timer(self, dispatcher, mock_interface):
        """Test setExpirationTimer handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "setExpirationTimer",
            {"number": "+491234567890", "expiration": 86400},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("setExpirationTimer", "si", ["+491234567890", 86400])


class TestMoreMessagingHandlers:
    """Additional messaging handler tests."""

    async def test_send_viewed_receipt(self, dispatcher, mock_interface):
        """Test sendViewedReceipt handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "sendViewedReceipt",
            {
                "recipient": "+491234567890",
                "targetSentTimestamps": [1234567890000],
            },
        )

        assert result is None
        mock_interface.call.assert_called_once_with("sendViewedReceipt", "sax", ["+491234567890", [1234567890000]])

    async def test_send_typing_start(self, dispatcher, mock_interface):
        """Test sendTyping with start."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "sendTyping",
            {"recipient": "+491234567890", "stop": False},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("sendTyping", "sb", ["+491234567890", False])

    async def test_send_typing_stop(self, dispatcher, mock_interface):
        """Test sendTyping with stop."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "sendTyping",
            {"recipient": "+491234567890", "stop": True},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("sendTyping", "sb", ["+491234567890", True])

    async def test_send_end_session(self, dispatcher, mock_interface):
        """Test sendEndSessionMessage handler."""
        mock_interface.call = AsyncMock(return_value=None)

        result = await dispatcher.dispatch(
            "sendEndSessionMessage",
            {"recipients": ["+491234567890"]},
        )

        assert result is None
        mock_interface.call.assert_called_once_with("sendEndSessionMessage", "as", [["+491234567890"]])

    async def test_send_payment_notification(self, dispatcher, mock_interface):
        """Test sendPaymentNotification handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        result = await dispatcher.dispatch(
            "sendPaymentNotification",
            {
                "receipt": "cmVjZWlwdA==",  # base64 of "receipt"
                "note": "Payment note",
                "recipient": "+491234567890",
            },
        )

        assert result == {"timestamp": 1234567890123}

    async def test_send_remote_delete(self, dispatcher, mock_interface):
        """Test sendRemoteDeleteMessage handler."""
        mock_interface.call = AsyncMock(return_value=1234567890123)

        result = await dispatcher.dispatch(
            "sendRemoteDeleteMessage",
            {
                "targetSentTimestamp": 1234567890000,
                "recipients": ["+491234567890"],
            },
        )

        assert result == {"timestamp": 1234567890123}


class TestIdentityHandlers:
    """Test identity method handlers."""

    async def test_list_identities(self, dispatcher, mock_interface):
        """Test listIdentities handler."""
        mock_interface.call = AsyncMock(
            return_value=[
                ["/org/asamk/Signal/Identities/1", "uuid-123", "+491234567890"],
            ]
        )

        result = await dispatcher.dispatch("listIdentities", {})

        assert len(result) == 1
        assert result[0]["uuid"] == "uuid-123"

    async def test_trust_identity(self, dispatcher, mock_client, mock_interface):
        """Test trustIdentity handler."""
        mock_identity_iface = MagicMock()
        mock_identity_iface.call = AsyncMock(return_value=None)
        mock_interface.call = AsyncMock(return_value="/org/asamk/Signal/Identities/1")
        mock_client.sub_interface = MagicMock(return_value=mock_identity_iface)

        result = await dispatcher.dispatch(
            "trustIdentity",
            {"number": "+491234567890"},
        )

        assert result is None
        mock_identity_iface.call.assert_called_once_with("trust", "", [])

    async def test_trust_identity_verified(self, dispatcher, mock_client, mock_interface):
        """Test trustIdentityVerified handler."""
        mock_identity_iface = MagicMock()
        mock_identity_iface.call = AsyncMock(return_value=None)
        mock_interface.call = AsyncMock(return_value="/org/asamk/Signal/Identities/1")
        mock_client.sub_interface = MagicMock(return_value=mock_identity_iface)

        result = await dispatcher.dispatch(
            "trustIdentityVerified",
            {"number": "+491234567890", "safetyNumber": "12345"},
        )

        assert result is None
        mock_identity_iface.call.assert_called_once_with("trustVerified", "s", ["12345"])


class TestCallErrorHandling:
    """Test that failed calls feed the connection-error classifier."""

    async def test_error_notified_to_client(self, dispatcher, mock_client, mock_interface):
        """Exceptions from handlers are reported via client.note_error."""
        from dbus_fast.errors import DBusError

        mock_interface.call = AsyncMock(side_effect=DBusError("org.freedesktop.DBus.Error.ServiceUnknown", "gone"))

        with pytest.raises(DBusError):
            await dispatcher.dispatch("version", {})

        mock_client.note_error.assert_called_once()

    async def test_timeout_notified_to_client(self, dispatcher, mock_client, mock_interface):
        """Hung calls raise TimeoutError and are reported as connection errors."""
        import asyncio

        async def hang(*args):
            await asyncio.sleep(60)

        mock_interface.call = AsyncMock(side_effect=hang)

        with patch("swb.dispatch.CALL_TIMEOUT", 0.05):
            with pytest.raises(TimeoutError):
                await dispatcher.dispatch("version", {})

        mock_client.note_error.assert_called_once()
