import unittest

from time_service import TimeSyncService


class FakeLocalNode:
    def __init__(self):
        self.num = 1
        self.times = []

    def setTime(self, timestamp=0):
        self.times.append(timestamp)


class FakeMeshInterface:
    def __init__(self):
        self.localNode = FakeLocalNode()


class TimeSyncServiceTests(unittest.TestCase):
    def test_rejects_epoch_zero_and_old_packet_times(self):
        service = TimeSyncService(clock=lambda: 1788830000)

        self.assertFalse(service.is_reasonable_timestamp(0))
        self.assertFalse(service.is_reasonable_timestamp(1560217041))

    def test_extracts_packet_time_candidates(self):
        service = TimeSyncService()
        packet = {
            "rxTime": 1788830000,
            "position": {"time": 1788830001},
            "decoded": {
                "position": {"timestamp": 1788830002},
                "telemetry": {"time": 1788830003},
            },
        }

        self.assertEqual(
            [1788830001, 1788830002, 1788830003],
            service.extract_packet_times(packet),
        )

    def test_can_extract_receive_time_when_explicitly_enabled(self):
        service = TimeSyncService({"allow_receive_time": True})

        self.assertEqual([1788830000], service.extract_packet_times({"rxTime": 1788830000}))

    def test_syncs_radio_from_host_clock(self):
        mesh_interface = FakeMeshInterface()
        service = TimeSyncService(clock=lambda: 1788830000)

        self.assertTrue(service.sync_from_host(mesh_interface))
        self.assertEqual([1788830000], mesh_interface.localNode.times)

    def test_syncs_radio_from_mesh_packet_and_throttles(self):
        mesh_interface = FakeMeshInterface()
        service = TimeSyncService(clock=lambda: 1788830100)

        self.assertTrue(service.sync_from_packet(mesh_interface, {"position": {"time": 1788830000}}))
        self.assertFalse(service.sync_from_packet(mesh_interface, {"position": {"time": 1788830001}}))
        self.assertEqual([1788830000], mesh_interface.localNode.times)

    def test_syncs_radio_from_known_node_position_time(self):
        mesh_interface = FakeMeshInterface()
        mesh_interface.nodes = {
            "!local": {"num": 1, "position": {"time": 1788830001}},
            "!neighbor": {"num": 2, "position": {"time": 1788830002}},
        }
        service = TimeSyncService(clock=lambda: 1788830100)

        self.assertTrue(service.sync_from_known_nodes(mesh_interface))
        self.assertEqual([1788830002], mesh_interface.localNode.times)


if __name__ == "__main__":
    unittest.main()
