# Copyright (c) 2018 Vexata Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Unit tests for Vexata Storage VX100 Arrays.
"""

import mock

from oslo_utils import units

from cinder import exception
from cinder.objects import fields
from cinder import test
from cinder.volume.drivers.vexata import vexata

SAN_HTTPS_PORT = 443
SAN_IP = 'testarray'
SAN_USER = 'testadmin'
SAN_PASS = 'testpass'
SAN_SSL_VERIFY_CERT = False
SAN_SSL_CERT_PATH = None
STORAGE_PROTOCOL = 'FC'
STORAGE_VENDOR = 'Vexata'
VEXATA_API = 'cinder.volume.drivers.vexata.vexata_api_proxy.VexataAPIProxy'
VOLUME_BACKEND_NAME = 'vexatafc'

IOCS_SUPPORTED = [
    {'id': 0, 'name': 'b787-ioc0', 'swVersion': 'v3.5.0-0_abcde',
     'mgmtRole': True},
    {'id': 1, 'name': 'b787-ioc1', 'swVersion': 'v3.5.0-0_abcde',
     'mgmtRole': False}]

IOCS_UNSUPPORTED = [
    {'id': 0, 'name': 'b787-ioc0', 'swVersion': 'v3.0.2-12_abcde',
     'mgmtRole': True},
    {'id': 1, 'name': 'b787-ioc1', 'swVersion': 'v3.0.2-12_abcde',
     'mgmtRole': False}]

VX_VOLUME_ID = 64
VX_VOLUME_SNAP_ID = 65
VX_VOLUME_CLONE_ID = 67
VOLUME1_UUID = '11111111-4444-4444-4444-ccccccccccccc'
VOLUME2_UUID = '11112222-4444-4444-4444-ccccccccccccc'
VOLUME3_UUID = '11113333-4444-4444-4444-ccccccccccccc'
VOLUME4_UUID = '11114444-4444-4444-4444-ccccccccccccc'
SNAP1_UUID = '22221111-4444-4444-4444-ccccccccccccc'
SNAP2_UUID = '22222222-4444-4444-4444-ccccccccccccc'
CG1_UUID = '55551111-4444-4444-4444-ccccccccccccc'
CG2_UUID = '55552222-4444-4444-4444-ccccccccccccc'
CGSNAP1_UUID = '77771111-4444-4444-4444-ccccccccccccc'

HTTP_NOT_FOUND = 404
HTTP_GET_OK = 200
HTTP_POST_OK = 201
HTTP_POST_OK2 = 204
HTTP_PUT_OK = 200
HTTP_DEL_OK = 204

# Openstack volume sizes are in GiB units
OS_VOLUME1 = mock.MagicMock(id=VOLUME1_UUID, size=2)
OS_VOLUME2 = mock.MagicMock(id=VOLUME2_UUID, size=4)
OS_VOLUME3 = mock.MagicMock(id=VOLUME3_UUID, size=2)
OS_VOLUME4 = mock.MagicMock(id=VOLUME4_UUID, size=4)
OS_VOLUME1_SNAP1 = mock.MagicMock(id=SNAP1_UUID, volume=OS_VOLUME1)
OS_CG1 = mock.MagicMock(id=CG1_UUID)
OS_CG2 = mock.MagicMock(id=CG2_UUID)
OS_CG_SNAP1 = mock.MagicMock(id=CGSNAP1_UUID, group=OS_CG1)

OS_MODEL_UPDT_OK = {'status': fields.GroupStatus.AVAILABLE}
OS_MODEL_UPDT_ERR = {'status': fields.GroupStatus.ERROR}

# Vexata sizes are in MiB units
VX_SAINFO = {
    'provisionCapacityLeft': 12288,
    'entityCounts': {
        'volumeCount': 8,
    },
    'description': 'Test Storage Array',
    'maxVolumeSize': 16777216,
    'maxProvisionLimit': 12288,
    'uuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    'usedCapacity': 1234,
    'state': 'ENABLED',
    'maxOverProvisioningFactor': 100,
    'provisionedCapacity': 5120,
    'minVolumeSize': 1,
    'thresholdPercentage': 75,
    'totalCapacity': 12288,
    'id': 0,
    'name': 'sa0',
}
VX_VOLUMES = [
    {
        'id': 64,
        'name': 'vol1',
        'description': 'Test vol1',
        'voluuid': VOLUME1_UUID,
        'volSize': OS_VOLUME1.size * units.Ki,
        'numOfSnapshots': 0,
        'volumeGroups': [0],
        'parentVolumeId': None,
    },
    {
        'id': 65,
        'name': 'vol2',
        'description': 'Test vol3',
        'voluuid': VOLUME2_UUID,
        'volSize': OS_VOLUME2.size * units.Ki,
        'numOfSnapshots': 0,
        'volumeGroups': [0],
        'parentVolumeId': None,
    },
]
VX_POST_RSP = {
    'id': 64,
}
VX_VG1 = {
    'name': 'vg1',
    'description': 'Test VG 1',
    'currVolumes': [VX_VOLUMES[0]['id']],
    'numOfVols': 1,
    'id': 0,
}
VX_VG_SNAP1 = {
    'id': 701,
    'name': 'vgsnap1',
    'parentVolumeGroupId': VX_VG1['id'],
    'description': 'test cg snap',
    'currSnapshots': [84, 85],
    'numOfSnapshots': 2,
    'exportGroups': []
}
VX_VG_CLONE1 = {
    'name': 'vgclone1',
    'description': 'Test VG clone 1',
    'currVolumes': [VX_VOLUMES[0]['id'] + 700],
    'numOfVols': 1,
    'id': 0,
}


def mock_responses(*args):
    # Each arg should be a (status_code, rsp_json) tuple
    rsps = [mock.MagicMock(status_code=tupl[0]) for tupl in args]
    for i, el in enumerate(rsps):
        el.json.return_value = args[i][1]
    return rsps


def fake_vx_vol(vx_vol_template, os_vol):
    vx_vol = vx_vol_template.copy()
    vx_vol['uuid'] = vx_vol['voluuid'] = os_vol.id
    vx_vol['volSize'] = os_vol.size * units.Ki
    return vx_vol


def fake_vx_snap(vx_vol_template, os_snap):
    vx_snap = vx_vol_template.copy()
    vx_snap['uuid'] = vx_snap['voluuid'] = os_snap.id
    vx_snap['volSize'] = os_snap.size * units.Ki
    vx_snap['parentVolumeId'] = vx_vol_template['id']
    vx_snap['id'] = 500 + vx_vol_template['id']
    return vx_snap


class TestCaseBase(test.TestCase):
    def setUp(self):
        super(TestCaseBase, self).setUp()
        self.config = mock.Mock()
        self.config.san_ip = SAN_IP
        self.config.san_login = SAN_USER
        self.config.san_password = SAN_PASS
        self.config.driver_ssl_cert_verify = SAN_SSL_VERIFY_CERT
        self.config.driver_ssl_cert_path = SAN_SSL_CERT_PATH
        self.config.vexata_https_port = SAN_HTTPS_PORT
        self.config.volume_backend_name = VOLUME_BACKEND_NAME


class PreSetupTestCase(TestCaseBase):
    def setUp(self):
        super(PreSetupTestCase, self).setUp()
        self.driver = vexata.VexataVX100FibreChannelDriver(
            configuration=self.config)

    @mock.patch(VEXATA_API)
    def test_do_setup(self, mock_api_cls):
        self.driver.do_setup(None)
        mock_api_cls.assert_called_once_with(
            mgmt_ip=SAN_IP,
            mgmt_user=SAN_USER,
            mgmt_passwd=SAN_PASS,
            mgmt_port=SAN_HTTPS_PORT,
            verify_cert=SAN_SSL_VERIFY_CERT,
            cert_path=SAN_SSL_CERT_PATH)


class SetupCheckTestCase(TestCaseBase):
    def setUp(self):
        super(SetupCheckTestCase, self).setUp()
        self.driver = vexata.VexataVX100FibreChannelDriver(
            configuration=self.config)
        self.driver.do_setup(None)

    # @TODO(sandeep): revisit after api raises exceptions on missing array
    @mock.patch('requests.request', autospec=True)
    def test_missing_array(self, mock_req):
        rsps = mock_responses((400, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.check_for_setup_error)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_unsupported_swversion_fails(self, mock_req):
        rsps = mock_responses((HTTP_GET_OK, IOCS_UNSUPPORTED))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.check_for_setup_error)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_supported_swversion(self, mock_req):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED))
        mock_req.side_effect = rsps
        self.driver.check_for_setup_error()
        self.assertEqual(mock_req.call_count, len(rsps))


class VolumesTestCase(TestCaseBase):
    def setUp(self):
        super(VolumesTestCase, self).setUp()
        self.driver = vexata.VexataVX100FibreChannelDriver(
            configuration=self.config)
        self.driver.do_setup(None)

    @mock.patch('requests.request', autospec=True)
    def test_get_volume_stats(self, mock_req):
        tot_cap_GiB = VX_SAINFO['totalCapacity'] / float(units.Ki)
        free_cap_GiB = ((VX_SAINFO['totalCapacity'] -
                         VX_SAINFO['usedCapacity']) / float(units.Ki))
        prov_cap_GiB = VX_SAINFO['provisionedCapacity'] / float(units.Ki)
        op_ratio = VX_SAINFO['maxOverProvisioningFactor'] / 100.0
        exp_result = dict(
            volume_backend_name=VOLUME_BACKEND_NAME,
            vendor_name=STORAGE_VENDOR,
            storage_protocol=STORAGE_PROTOCOL,
            total_capacity_gb=tot_cap_GiB,
            free_capacity_gb=free_cap_GiB,
            reserved_percentage=0,
            provisioned_capacity_gb=prov_cap_GiB,
            max_over_subscription_ratio=op_ratio,
            thin_provisioning_support=True,
            thick_provisioning_support=False,
            multiattach=False
        )
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              (HTTP_GET_OK, VX_SAINFO))
        mock_req.side_effect = rsps
        result = self.driver.get_volume_stats(refresh=True)
        self.assertDictContainsSubset(exp_result, result)
        self.assertEqual(mock_req.call_count, len(rsps))
        # refresh=False should return same data but not make any api calls
        mock_req.reset_mock()
        result = self.driver.get_volume_stats(refresh=False)
        self.assertDictContainsSubset(exp_result, result)
        self.assertEqual(mock_req.call_count, 0)

    @mock.patch('requests.request', autospec=True)
    def test_create_volume(self, mock_req):
        rsps = mock_responses((HTTP_POST_OK, VX_POST_RSP))
        mock_req.side_effect = rsps
        self.driver.create_volume(OS_VOLUME1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_extend_volume(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_GET_OK, None))
        mock_req.side_effect = rsps
        self.driver.extend_volume(OS_VOLUME1, OS_VOLUME1.size * 2)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_extend_volume_fails_not_found(self, mock_req):
        rsps = mock_responses((HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.extend_volume,
            OS_VOLUME1, OS_VOLUME1.size * 2)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_extend_volume_fails_smaller(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.extend_volume,
            OS_VOLUME1, OS_VOLUME1.size / 2)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_volume(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        self.driver.delete_volume(OS_VOLUME1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_volume_fails_vol_deleted(self, mock_req):
        rsps = mock_responses((HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_volume,
            OS_VOLUME1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_volume_fails_has_snaps(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        vx_vol['numOfSnapshots'] = 1
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeIsBusy,
            self.driver.delete_volume,
            OS_VOLUME1)
        self.assertEqual(mock_req.call_count, len(rsps))


class SnapsTestCase(TestCaseBase):
    def setUp(self):
        super(SnapsTestCase, self).setUp()
        self.driver = vexata.VexataVX100FibreChannelDriver(
            configuration=self.config)
        self.driver.do_setup(None)

    @mock.patch('requests.request', autospec=True)
    def test_create_snapshot(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_POST_OK, VX_POST_RSP))
        mock_req.side_effect = rsps
        self.driver.create_snapshot(OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_snapshot(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        vx_snap = fake_vx_snap(VX_VOLUMES[0], OS_VOLUME1_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_GET_OK, [vx_snap]),
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        self.driver.delete_snapshot(OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_snapshot_fails_parentvol_deleted(self, mock_req):
        rsps = mock_responses((HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_snapshot,
            OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_delete_snapshot_fails_snap_deleted(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_snapshot,
            OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_revert_to_snapshot(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        vx_snap = fake_vx_snap(VX_VOLUMES[0], OS_VOLUME1_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_GET_OK, [vx_snap]),
                              (HTTP_POST_OK2, VX_POST_RSP))
        mock_req.side_effect = rsps
        self.driver.revert_to_snapshot(None, OS_VOLUME1, OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_revert_to_snapshot_fails_parentvol_deleted(self, mock_req):
        rsps = mock_responses((HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.revert_to_snapshot,
            None, OS_VOLUME1, OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_revert_to_snapshot_fails_snap_deleted(self, mock_req):
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.revert_to_snapshot,
            None, OS_VOLUME1, OS_VOLUME1_SNAP1)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_create_volume_from_snapshot(self, mock_req):
        vol = OS_VOLUME1.copy()
        vol.size = OS_VOLUME2.size
        snap = mock.MagicMock(id=SNAP1_UUID, volume=vol)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], vol)
        vx_snap = fake_vx_snap(VX_VOLUMES[0], snap)
        vx_new_vol = fake_vx_vol(VX_VOLUMES[1], OS_VOLUME2)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_GET_OK, [vx_snap]),
                              (HTTP_POST_OK, vx_new_vol))
        mock_req.side_effect = rsps
        self.driver.create_volume_from_snapshot(OS_VOLUME2, snap)
        self.assertEqual(mock_req.call_count, len(rsps))

    # Backend clone expand not supported on array
    @mock.patch('requests.request', autospec=True)
    def test_create_volume_from_snapshot_fails_vol_expand(self, mock_req):
        vol = OS_VOLUME1.copy()
        vol.size = OS_VOLUME2.size - 1
        snap = mock.MagicMock(id=SNAP1_UUID, volume=vol)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], vol)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume_from_snapshot,
            OS_VOLUME2, snap)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_create_volume_from_snapshot_fails_vol_shrink(self, mock_req):
        # Openstack thinks size is A but behind the scenes vol has already
        # been expanded A+B, so it will look like a shrink for array.
        vol = OS_VOLUME1.copy()
        vol.size = OS_VOLUME2.size - 1
        snap = mock.MagicMock(id=SNAP1_UUID, volume=vol)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], vol)
        vx_vol['volSize'] += 1
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_volume_from_snapshot,
            OS_VOLUME2, snap)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_create_cloned_volume(self, mock_req):
        vol = OS_VOLUME1.copy()
        vol.size = OS_VOLUME2.size
        snap = mock.MagicMock(id=SNAP1_UUID, volume=vol)
        src_vref = dict(id=vol.id, size=vol.size)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], vol)
        vx_snap = fake_vx_snap(VX_VOLUMES[0], snap)
        vx_new_vol = fake_vx_vol(VX_VOLUMES[1], OS_VOLUME2)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]),
                              (HTTP_POST_OK, vx_snap),
                              (HTTP_POST_OK, vx_new_vol),
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        self.driver.create_cloned_volume(OS_VOLUME2, src_vref)
        self.assertEqual(mock_req.call_count, len(rsps))

    # Backend clone expand not supported on array
    @mock.patch('requests.request', autospec=True)
    def test_create_cloned_volume_fails_clone_expand(self, mock_req):
        vol = OS_VOLUME1.copy()
        vol.size -= 1
        src_vref = dict(id=vol.id, size=vol.size)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], vol)
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_cloned_volume,
            OS_VOLUME2, src_vref)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('requests.request', autospec=True)
    def test_create_cloned_volume_fails_clone_shrink(self, mock_req):
        # Openstack thinks size is A but behind the scenes vol has already
        # been expanded A+B, so it will look like a shrink for array.
        src_vref = dict(id=OS_VOLUME2.id, size=OS_VOLUME2.size)
        vx_vol = fake_vx_vol(VX_VOLUMES[0], OS_VOLUME1)
        vx_vol['volSize'] = OS_VOLUME2.size + 1
        rsps = mock_responses((HTTP_GET_OK, [vx_vol]))
        mock_req.side_effect = rsps
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_cloned_volume,
            OS_VOLUME2, src_vref)
        self.assertEqual(mock_req.call_count, len(rsps))


class GroupsTestCase(TestCaseBase):
    def setUp(self):
        super(GroupsTestCase, self).setUp()
        self.driver = vexata.VexataVX100FibreChannelDriver(
            configuration=self.config)
        self.driver.do_setup(None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group,
            None, OS_CG1)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_group_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group,
            None, OS_CG1, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_update_group_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            None, OS_CG1, None, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_from_src_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.update_group,
            None, OS_CG1, None, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_create_group_snapshot_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.create_group_snapshot,
            None, OS_CG_SNAP1, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=False)
    def test_delete_group_snapshot_fails_noncg(self, *other_mocks):
        self.assertRaises(
            NotImplementedError,
            self.driver.delete_group_snapshot,
            None, OS_CG_SNAP1, None)

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group(self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED))
        mock_req.side_effect = rsps
        model_update = self.driver.create_group(None, OS_CG1)
        self.assertDictEqual(model_update, OS_MODEL_UPDT_OK)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_noop(self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[], remove_volumes=[])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertIsNone(add_vols_updt)
        self.assertIsNone(rm_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_add_vols_fails_vol_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # missing add_volume: deleted on backend ?
                              (HTTP_NOT_FOUND, []))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[OS_VOLUME1], remove_volumes=[])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(add_vols_updt)
        self.assertIsNone(rm_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_add_vols_new_vg(self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found add_volume
                              (HTTP_GET_OK, [VX_VOLUMES[0]]),
                              # vg does not exist yet
                              (HTTP_GET_OK, []),
                              # create vg
                              (HTTP_POST_OK, VX_VG1))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[OS_VOLUME1], remove_volumes=[])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(add_vols_updt, [{'id': OS_VOLUME1.id}])
        self.assertEqual(rm_vols_updt, [])
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_add_vols_existing_vg(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        updt_vg = test_vg.copy()
        updt_vg['currVolumes'] = []
        updt_vg['numOfVols'] = 0
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found add_volume
                              (HTTP_GET_OK, [VX_VOLUMES[0]]),
                              # vg exists
                              (HTTP_GET_OK, [test_vg]),
                              # modify vg
                              (HTTP_PUT_OK, updt_vg))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[OS_VOLUME1], remove_volumes=[])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(add_vols_updt, [{'id': OS_VOLUME1.id}])
        self.assertEqual(rm_vols_updt, [])
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_rm_vols_fails_vol_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # missing rm_volume: deleted on backend ?
                              (HTTP_NOT_FOUND, []))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[], remove_volumes=[OS_VOLUME1])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(add_vols_updt)
        self.assertIsNone(rm_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_rm_vols_existing_vg(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        updt_vg = test_vg.copy()
        updt_vg['currVolumes'] = []
        updt_vg['numOfVols'] = 0
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found rm_volume
                              (HTTP_GET_OK, [VX_VOLUMES[0]]),
                              # vg exists
                              (HTTP_GET_OK, [test_vg]),
                              # modify vg
                              (HTTP_PUT_OK, updt_vg))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1, add_volumes=[], remove_volumes=[OS_VOLUME1])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(add_vols_updt, [])
        self.assertEqual(rm_vols_updt, [{'id': OS_VOLUME1.id}])
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_update_group_addrm_vols_fails_vg_not_found(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        updt_vg = test_vg.copy()
        updt_vg['currVolumes'] = []
        updt_vg['numOfVols'] = 0
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found add_volume
                              (HTTP_GET_OK, [VX_VOLUMES[0]]),
                              # found rm_volume
                              (HTTP_GET_OK, [VX_VOLUMES[1]]),
                              # vg not found
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, add_vols_updt, rm_vols_updt = self.driver.update_group(
            None, OS_CG1,
            add_volumes=[OS_VOLUME1], remove_volumes=[OS_VOLUME2])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(add_vols_updt)
        self.assertIsNone(rm_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_no_vols(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg['exportGroups'] = []
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg found
                              (HTTP_GET_OK, [test_vg]),
                              # vg deleted
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_no_vols_vg_deleted(self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg already deletd on backend
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_vols_fails_vg_in_eg(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg['exportGroups'] = [0, 1]
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg found
                              (HTTP_GET_OK, [test_vg]))
        mock_req.side_effect = rsps
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [OS_VOLUME1, OS_VOLUME2])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_vols(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg['exportGroups'] = []
        test_vol1 = VX_VOLUMES[0].copy()
        test_vol1['volumeGroups'] = []
        test_vol2 = VX_VOLUMES[1].copy()
        test_vol2['volumeGroups'] = []
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg found
                              (HTTP_GET_OK, [test_vg]),
                              # vg deleted
                              (HTTP_DEL_OK, None),
                              # found volumes to be  deleted
                              (HTTP_GET_OK, [test_vol1]),
                              (HTTP_GET_OK, [test_vol2]),
                              # delete volumes
                              (HTTP_DEL_OK, None),
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        exp_vols_updt = [{'id': v['voluuid'],
                          'status': fields.GroupStatus.DELETED}
                         for v in [test_vol1, test_vol2]]
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [OS_VOLUME1, OS_VOLUME2])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(vols_updt, exp_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_vols_fails_vol_not_found(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg['exportGroups'] = []
        test_vol1 = VX_VOLUMES[0].copy()
        test_vol1['volumeGroups'] = []
        test_vol2 = VX_VOLUMES[1].copy()
        test_vol2['volumeGroups'] = []
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg found
                              (HTTP_GET_OK, [test_vg]),
                              # vg deleted
                              (HTTP_DEL_OK, None),
                              # found 1 of 2 volumes to be  deleted
                              (HTTP_GET_OK, [test_vol1]),
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [OS_VOLUME1, OS_VOLUME2])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_vols_fails_vol_in_vg(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg['exportGroups'] = []
        test_vol1 = VX_VOLUMES[0].copy()
        test_vol1['volumeGroups'] = [1, 3]
        test_vol2 = VX_VOLUMES[1].copy()
        test_vol2['volumeGroups'] = []
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg found
                              (HTTP_GET_OK, [test_vg]),
                              # vg deleted
                              (HTTP_DEL_OK, None),
                              # found volumes to be  deleted
                              (HTTP_GET_OK, [test_vol1]),
                              (HTTP_GET_OK, [test_vol2]),
                              # delete volume 2 only
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        exp_vols_updt = [{'id': test_vol1['voluuid'],
                          'status': fields.GroupStatus.ERROR_DELETING},
                         {'id': test_vol2['voluuid'],
                          'status': fields.GroupStatus.DELETED}]
        model_updt, vols_updt = self.driver.delete_group(
            None, OS_CG1, [OS_VOLUME1, OS_VOLUME2])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(vols_updt, exp_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_snapshot(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg_snap = VX_VG_SNAP1.copy()
        test_vg_snap['name'] = self.driver.make_cgsnap_name(OS_CG_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # create vg snap
                              (HTTP_POST_OK, test_vg_snap))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.create_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_snapshot_fails_vg_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg not found
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.create_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_snapshot_fails_vgsnap_err(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # failed to create vg snap
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.create_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_snapshot(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg_snap = VX_VG_SNAP1.copy()
        test_vg_snap['name'] = self.driver.make_cgsnap_name(OS_CG_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # found vg snap
                              (HTTP_GET_OK, [test_vg_snap]),
                              # delete vg snap
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.delete_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_snapshot_fails_vg_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg not found
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.delete_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_snapshot_fails_vgsnap_not_found(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # did not find vg snap
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.delete_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_delete_group_snapshot_fails_rm_vgsnap_err(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        test_vg_snap = VX_VG_SNAP1.copy()
        test_vg_snap['name'] = self.driver.make_cgsnap_name(OS_CG_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # found vg snap
                              (HTTP_GET_OK, [test_vg_snap]),
                              # could not delete vg snap
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        model_updt, snaps_updt = self.driver.delete_group_snapshot(
            None, OS_CG_SNAP1, [mock.MagicMock()])
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(snaps_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cg(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        tmp_vg_snap = VX_VG_SNAP1.copy()
        test_vg_clone = test_vg.copy()
        test_vg_clone['name'] = self.driver.make_cg_name(OS_CG2)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # create tmp vg snap
                              (HTTP_POST_OK, tmp_vg_snap),
                              # cloned new vg
                              (HTTP_POST_OK, test_vg_clone),
                              # deleted tmp vg snap
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        cur_os_volumes = [OS_VOLUME1, OS_VOLUME2]
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        exp_vols_updt = [{'id': v.id, 'status': fields.GroupStatus.AVAILABLE}
                         for v in new_os_volumes]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=None, snapshots=None,
            source_group=OS_CG1, source_vols=cur_os_volumes)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(vols_updt, exp_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cg_fails_vg_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # did not find vg
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        cur_os_volumes = [OS_VOLUME1, OS_VOLUME2]
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=None, snapshots=None,
            source_group=OS_CG1, source_vols=cur_os_volumes)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cg_fails_vgsnap_err(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # create tmp vg snap fails
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        cur_os_volumes = [OS_VOLUME1, OS_VOLUME2]
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=None, snapshots=None,
            source_group=OS_CG1, source_vols=cur_os_volumes)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cg_fails_vgclone_err(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG1)
        tmp_vg_snap = VX_VG_SNAP1.copy()
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # create tmp vg snap
                              (HTTP_POST_OK, tmp_vg_snap),
                              # fails to clone new vg
                              (HTTP_NOT_FOUND, None),
                              # deleted tmp vg snap
                              (HTTP_DEL_OK, None))
        mock_req.side_effect = rsps
        cur_os_volumes = [OS_VOLUME1, OS_VOLUME2]
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=None, snapshots=None,
            source_group=OS_CG1, source_vols=cur_os_volumes)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cgsnap(self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG_SNAP1.group)
        test_vg_snap = VX_VG_SNAP1.copy()
        test_vg_snap['name'] = self.driver.make_cgsnap_name(OS_CG_SNAP1)
        test_vg_clone = test_vg.copy()
        test_vg_clone['name'] = self.driver.make_cg_name(OS_CG2)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # find vg snap
                              (HTTP_GET_OK, [test_vg_snap]),
                              # cloned new vg
                              (HTTP_POST_OK, test_vg_clone))
        mock_req.side_effect = rsps
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        exp_vols_updt = [{'id': v.id, 'status': fields.GroupStatus.AVAILABLE}
                         for v in new_os_volumes]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=OS_CG_SNAP1, snapshots=[mock.Mock(), mock.Mock()],
            source_group=None, source_vols=None)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_OK)
        self.assertEqual(vols_updt, exp_vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cgsnap_fails_vg_not_found(
            self, mock_req, *other_mocks):
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # vg not found
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=OS_CG_SNAP1, snapshots=[mock.Mock(), mock.Mock()],
            source_group=None, source_vols=None)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cgsnap_fails_vgsnap_not_found(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG_SNAP1.group)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # failed to find vg snap
                              (HTTP_GET_OK, []))
        mock_req.side_effect = rsps
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=OS_CG_SNAP1, snapshots=[mock.Mock(), mock.Mock()],
            source_group=None, source_vols=None)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))

    @mock.patch('cinder.volume.utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch('requests.request', autospec=True)
    def test_create_group_from_src_cgsnap_fails_vgclone_err(
            self, mock_req, *other_mocks):
        test_vg = VX_VG1.copy()
        test_vg['name'] = self.driver.make_cg_name(OS_CG_SNAP1.group)
        test_vg_snap = VX_VG_SNAP1.copy()
        test_vg_snap['name'] = self.driver.make_cgsnap_name(OS_CG_SNAP1)
        rsps = mock_responses((HTTP_GET_OK, IOCS_SUPPORTED),
                              # found vg
                              (HTTP_GET_OK, [test_vg]),
                              # find vg snap
                              (HTTP_GET_OK, [test_vg_snap]),
                              # failed to clone new vg
                              (HTTP_NOT_FOUND, None))
        mock_req.side_effect = rsps
        new_os_volumes = [OS_VOLUME3, OS_VOLUME4]
        model_updt, vols_updt = self.driver.create_group_from_src(
            None, OS_CG2, new_os_volumes,
            group_snapshot=OS_CG_SNAP1, snapshots=[mock.Mock(), mock.Mock()],
            source_group=None, source_vols=None)
        self.assertDictEqual(model_updt, OS_MODEL_UPDT_ERR)
        self.assertIsNone(vols_updt)
        self.assertEqual(mock_req.call_count, len(rsps))
