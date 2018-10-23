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
Volume Driver for Vexata Storage Arrays.
Supports VX100 series.
"""

import uuid

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units

from cinder import exception as exc
from cinder import interface
from cinder.objects import fields
from cinder import utils as cinder_utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.vexata import vexata_api_proxy as api_proxy
from cinder.volume import manager
from cinder.volume import utils as vol_utils
from cinder.zonemanager import utils as fczm_utils


DRV_VERSION = "1.0.0"
DEFAULT_MGMT_PORT = 443

LOG = logging.getLogger(__name__)

vexata_opts = [
    cfg.IntOpt('vexata_https_port',
               default=443,
               help='HTTPS port to connect to Vexata API'),
]

CONF = cfg.CONF
CONF.register_opts(vexata_opts, group=configuration.SHARED_CONF_GROUP)

MAX_NAME_LEN = 31
MAX_DESC_LEN = 63
CNDR_VOLNAME = 'OS_vol'
CNDR_VOLDESC = 'OS_volume'
CNDR_SNPNAME = 'OS_snp'
CNDR_SNPDESC = 'OS_snap'
CNDR_CGNAME = 'OS_cg'
CNDR_CGDESC = 'OS_cg'
CNDR_CGSNAPNAME = 'OS_cgsnp'
CNDR_CGSNAPDESC = 'OS_cgsnap'
MIN_VERSION = (3, 5, 0)
MIN_CG_VERSION = (3, 5, 0)


def vx2cinder_wwn(wwn):
    # wwn is 00:11:22:33:44:55:66:77
    if ':' in wwn:
        return wwn.replace(':', '')
    else:
        return wwn


def cinder2vx_wwn(wwn):
    # wwn is 0011223344556677
    if ':' in wwn:
        return wwn
    else:
        return ':'.join([wwn[i:i + 2] for i in range(0, len(wwn), 2)])


class VgNotFoundException(Exception):
    pass


class MultipleVgsMatchedException(Exception):
    pass


class VgsnapNotFoundException(Exception):
    pass


class MultipleVgsnapsMatchedException(Exception):
    pass


class VexataVX100BaseDriver(san.SanDriver):
    """Vexata volume driver base functionality.

    """
    VERSION = DRV_VERSION
    # TODO(sandeep): ThirdPartySystems wiki page
    CI_WIKI_NAME = "Vexata_VX100_CI"

    def __init__(self, *args, **kwargs):
        super(VexataVX100BaseDriver, self).__init__(*args, **kwargs)
        self._api_proxy = None
        self._storage_protocol = None
        self._array_info = None
        self._swversion = None
        self.configuration.append_config_values(vexata_opts)
        self._backend_name = (self.configuration.volume_backend_name or
                              self.__class__.__name__)

    @staticmethod
    def _make_label(uuid, prefix, max_len):
        uuid32 = uuid.replace('-', '')
        name = '%s_%s' % (prefix, uuid32)
        return name[:max_len]

    @staticmethod
    def make_volume_name(volume):
        return VexataVX100BaseDriver._make_label(
            volume.id, CNDR_VOLNAME, MAX_NAME_LEN)

    @staticmethod
    def make_snap_name(snapshot):
        return VexataVX100BaseDriver._make_label(
            snapshot.id, CNDR_SNPNAME, MAX_NAME_LEN)

    @staticmethod
    def make_cg_name(cg):
        return VexataVX100BaseDriver._make_label(
            cg.id, CNDR_CGNAME, MAX_NAME_LEN)

    @staticmethod
    def make_cgsnap_name(cgsnap):
        return VexataVX100BaseDriver._make_label(
            cgsnap.id, CNDR_CGSNAPNAME, MAX_NAME_LEN)

    @staticmethod
    def make_volume_desc(volume):
        return VexataVX100BaseDriver._make_label(
            volume.id, CNDR_VOLDESC, MAX_DESC_LEN)

    @staticmethod
    def make_snap_desc(snapshot):
        return VexataVX100BaseDriver._make_label(
            snapshot.id, CNDR_SNPDESC, MAX_DESC_LEN)

    @staticmethod
    def make_cg_desc(cg):
        return VexataVX100BaseDriver._make_label(
            cg.id, CNDR_CGDESC, MAX_DESC_LEN)

    @staticmethod
    def make_cgsnap_desc(cgsnap):
        return VexataVX100BaseDriver._make_label(
            cgsnap.id, CNDR_CGSNAPDESC, MAX_DESC_LEN)

    def _load_swversion(self):
        # @TODO(sandeep): have api raise exceptions on connection problems
        self._swversion = (-1, -1, -1)
        iocs = self._api_proxy.iocs()
        if not iocs:
            msg = 'Unable to query IOC information'
            LOG.error(msg)
            raise exc.VolumeBackendAPIException(data=msg)
        active = filter(lambda x: x['mgmtRole'], iocs)
        if not active:
            msg = 'Unable to find active IOC'
            LOG.error(msg)
            raise exc.VolumeBackendAPIException(data=msg)
        active = active[0]
        ver = active['swVersion']
        assert ver[0] == 'v'
        ver = ver[1:ver.find('-')]
        ver = map(int, ver.split('.'))
        self._swversion = tuple(ver)
        if self._swversion < MIN_VERSION:
            msg = ('Vexata array version is too old and does not meet '
                   'minimum driver requirements.')
            LOG.error(msg)
            raise exc.VolumeBackendAPIException(data=msg)

    def _create_initiators(self, ini_wwns):
        ini_ids = []
        for wwn in ini_wwns:
            vxwwn = cinder2vx_wwn(wwn)
            rsp = self._api_proxy.add_initiator(
                'cndrini_%s' % vx2cinder_wwn(wwn),
                'Cinder created initiator',
                vxwwn)
            ini_ids.append(rsp['id'])
            LOG.debug('Created initiator %(id)d for %(wwn)s',
                      {'wwn': vxwwn, 'id': ini_ids[-1]})
        return ini_ids

    def _create_vg(self, vol_ids):
        vg_name = 'cndrvg_%s' % str(uuid.uuid4()).replace('-', '')[:20]
        new_vg = self._api_proxy.create_vg(vg_name,
                                           'Cinder created vg',
                                           vol_ids)
        LOG.debug('Created vg %(id)d with vol_ids %(vol_ids)s',
                  {'vol_ids': vol_ids, 'id': new_vg['id']})
        return new_vg

    def _create_ig(self, ini_ids):
        ig_name = 'cndrig_%s' % str(uuid.uuid4()).replace('-', '')[:20]
        ig_inis = sorted(list(ini_ids))
        new_ig = self._api_proxy.create_ig(ig_name,
                                           'Cinder created ig',
                                           ig_inis)
        LOG.debug('Created ig %(id)d for initiator ids %(ini_ids)s',
                  {'ini_ids': ig_inis, 'id': new_ig['id']})
        return new_ig

    def _create_pg(self, saport_ids):
        pg_name = 'cndrpg_%s' % str(uuid.uuid4()).replace('-', '')[:20]
        pg_ports = sorted(list(saport_ids))
        new_pg = self._api_proxy.create_pg(pg_name,
                                           'Cinder created pg',
                                           pg_ports)
        LOG.debug('Created pg %(id)d for target port ids %(tgt_ids)s',
                  {'tgt_ids': pg_ports, 'id': new_pg['id']})
        return new_pg

    def _create_eg(self, vg_id, ig_id, pg_id):
        eg_name = 'cndreg_%(vg)d_%(ig)d_%(pg)d' % {'vg': vg_id,
                                                   'ig': ig_id,
                                                   'pg': pg_id}
        eg_tuple = tuple((vg_id, ig_id, pg_id))
        new_eg = self._api_proxy.create_eg(eg_name,
                                           'Cinder created eg',
                                           eg_tuple)
        LOG.debug('Created eg %(id)d for tuple %(triple)s',
                  {'triple': eg_tuple, 'id': new_eg['id']})
        return new_eg

    @cinder_utils.trace
    def _find_volumes(self, cndr_volumes, vxid_only=False):
        vol_uuids = [vol.id for vol in cndr_volumes]
        vxvols = []
        for vol_uuid in vol_uuids:
            vol = self._api_proxy.find_volume_by_uuid(vol_uuid)
            if vol:
                id = vol[0]['id']
                if vxid_only:
                    vxvols.append(id)
                else:
                    vxvols.append(vol[0])
                LOG.debug('Found volume %(id)d with UUID %(uuid)s ',
                          {'uuid': vol_uuid, 'id': id})
            else:
                LOG.error('Volume with UUID %(uuid)s not found on array',
                          {'uuid': vol_uuid})
        return vxvols

    @cinder_utils.trace
    def _find_initiators(self, ini_wwns, create_missing=False):
        # ini_wwns are in Cinder format
        reqd_wwns = [cinder2vx_wwn(ini_wwn) for ini_wwn in ini_wwns]
        reqd_wwns_map = {wwn: 0 for wwn in reqd_wwns}
        found_ini_ids = []
        # Check existing initiators
        initiators = self._api_proxy.list_initiators()
        for ini in initiators:
            wwn = ini['memberId']
            if wwn in reqd_wwns_map:
                found_ini_ids.append(ini['id'])
                reqd_wwns_map[wwn] += 1
                LOG.debug('Found initiator %(id)d for %(wwn)s',
                          {'wwn': wwn, 'id': ini['id']})
        m = reqd_wwns_map
        missing_wwns = [mwwn for mwwn in m.keys() if m[mwwn] == 0]
        if missing_wwns:
            if create_missing:
                ids = self._create_initiators(missing_wwns)
                found_ini_ids.extend(ids)
            else:
                LOG.error('Missing initiators %(ini_wwns)s on array',
                          {'ini_wwns': missing_wwns})
                return None
        return found_ini_ids

    @cinder_utils.trace
    def _find_saports(self, tgt_wwns):
        # tgt_wwns are in Cinder format
        reqd_wwns = [cinder2vx_wwn(tgt_wwn) for tgt_wwn in tgt_wwns]
        saports = self._api_proxy.list_saports()
        reqd_wwns_set = set(reqd_wwns)
        found_saport_ids = []
        # Check existing saports
        for saport in saports:
            wwn = saport['name']
            if wwn in reqd_wwns_set:
                found_saport_ids.append(saport['id'])
                reqd_wwns_set.remove(wwn)
                # LOG.debug('Found tgt port %(id)d for %(wwn)s',
                #          {'wwn': wwn, 'id': saport['id']})
        # tgt_wwns should be obtained from the array => should never happen
        if len(reqd_wwns_set):
            LOG.error('Cannot find storage array target ports for %(wwns)s',
                      {'wwns': list(reqd_wwns_set)})
            return None
        return found_saport_ids

    @cinder_utils.trace
    def _find_igs(self, ini_ids):
        matching_ids = sorted(ini_ids)
        found_igs = []
        igs = self._api_proxy.list_igs()
        for ig in igs:
            member_ids = set(ig['currInitiators'])
            if sorted(member_ids) == matching_ids:
                found_igs.append(ig)
                LOG.debug('Found ig %(id)d for initiator ids %(ini_ids)s: ',
                          {'ini_ids': sorted(list(ini_ids)), 'id': ig['id']})
        return found_igs

    @cinder_utils.trace
    def _find_pgs(self, saport_ids):
        saport_id_set = set(saport_ids)
        found_pgs = []
        pgs = self._api_proxy.list_pgs()
        for pg in pgs:
            port_ids = set(pg['currPorts'])
            if port_ids == saport_id_set:
                found_pgs.append(pg)
                LOG.debug('Found pg %(id)d for target port ids %(tgt_ids)s',
                          {'tgt_ids': sorted(list(saport_ids)),
                           'id': pg['id']})
        return found_pgs

    @cinder_utils.trace
    def _find_vgs(self, vol_ids):
        reqd_vol_ids = sorted(vol_ids)
        found_vgs = []
        vgs = self._api_proxy.list_vgs()
        for vg in vgs:
            vol_ids = sorted(vg['currVolumes'])
            if reqd_vol_ids == vol_ids:
                found_vgs.append(vg)
                LOG.debug('Found vg %(id)d with vol_ids %(vol_ids)s',
                          {'vol_ids': reqd_vol_ids, 'id': vg['id']})
        return found_vgs

    @cinder_utils.trace
    def _get_vgs_in_egs(self, vgs, egs):
        """Get all vgs from the list that are members of the given egs.

        """
        vg_ids_from_egs = frozenset(eg['exportGroup3Tuple']['vgId']
                                    for eg in egs)
        return [vg for vg in vgs if vg['id'] in vg_ids_from_egs]

    @cinder_utils.trace
    def _find_vg_by_name(self, vg_name, err_missing=True):
        # Cannot query by vg id as we can't store information in Cinder db.
        # This could be expensive if there are many vgs and vgsnaps.
        all_vgs = self._api_proxy.list_vgs()
        vgs = filter(lambda vg: vg['name'] == vg_name, all_vgs)
        if not vgs:
            msg = 'Matching vg with name %s not found'
            if err_missing:
                LOG.error(msg, vg_name)
            raise VgNotFoundException(msg % vg_name)
        elif len(vgs) > 1:
            # found multiple vgs: multiple UUIDs had the same prefix bits !
            msg = 'Multiple vgs found with name %s'
            LOG.error(msg, vg_name)
            raise MultipleVgsMatchedException(msg % vg_name)
        return vgs[0]

    @cinder_utils.trace
    def _find_vgsnap_by_name(self, vg_id, vgsnap_name):
        # Cannot query by vg id as we can't store information in Cinder db.
        # This could be expensive if there are many vgs or vgsnaps
        all_vgsnaps = self._api_proxy.list_vgsnaps(vg_id)
        vgsnaps = filter(lambda snap: snap['name'] == vgsnap_name,
                         all_vgsnaps)
        if not vgsnaps:
            msg = 'Matching vg snapshot with name %s not found'
            LOG.error(msg, vgsnap_name)
            raise VgsnapNotFoundException(msg % vgsnap_name)
        elif len(vgsnaps) > 1:
            # found multiple vgsnaps: multiple UUIDs had the same prefix bits !
            msg = 'Multiple vg snapshots found with name %s'
            LOG.error(msg, vgsnap_name)
            raise MultipleVgsnapsMatchedException(msg % vgsnap_name)
        return vgsnaps[0]

    @cinder_utils.trace
    def _find_egs_with_igs_pgs(self, igs, pgs):
        """Find all eg that have any one of the igs + pgs as members.

        """
        eg_id_set = set()
        for ig in igs:
            ig_eg_ids = set(ig['exportGroups'])
            if not ig_eg_ids:
                continue
            for pg in pgs:
                pg_eg_ids = set(pg['exportGroups'])
                if not pg_eg_ids:
                    continue
                # egs containing this ig and pg
                common_eg_ids = ig_eg_ids.intersection(pg_eg_ids)
                eg_id_set.update(common_eg_ids)
        if not eg_id_set:
            return []
        found_egs = []
        all_egs = self._api_proxy.list_egs()
        for eg in all_egs:
            if eg['id'] in eg_id_set:
                found_egs.append(eg)
        return found_egs

    @cinder_utils.trace
    def _find_egs_with_pgs(self, pgs):
        """Find all eg that have any one of the pgs as members.

        """
        eg_id_set = set()
        for pg in pgs:
            pg_eg_ids = set(pg['exportGroups'])
            eg_id_set.update(pg_eg_ids)
        if not eg_id_set:
            return []
        found_egs = []
        all_egs = self._api_proxy.list_egs()
        for eg in all_egs:
            if eg['id'] in eg_id_set:
                found_egs.append(eg)
        return found_egs

    @cinder_utils.trace
    def _add_vols_to_eg_vg(self, eg, vol_ids):
        vg_id = eg['exportGroup3Tuple']['vgId']
        # Need name and desc to modify members !
        vg = self._api_proxy.find_vg_by_id(vg_id)
        if not vg:
            LOG.error('Failed to find vg %d', vg_id)
            return False
        rsp = self._api_proxy.modify_vg(
            vg_id,
            vg['name'],
            vg['description'],
            add_vol_ids=vol_ids,
            rm_vol_ids=[]
        )
        if rsp is None:
            LOG.error('Failed to add volumes %(vols)s to vg %(id)d',
                      {'vols': vol_ids, 'id': vg_id})
            return False
        else:
            LOG.debug('Added volumes %(vols)s to vg %(id)d',
                      {'vols': vol_ids, 'id': vg_id})
            return True

    @cinder_utils.trace
    def _find_volume_by_uuid(self, volume_uuid):
        rsp = self._api_proxy.find_volume_by_uuid(volume_uuid)
        if rsp is None or len(rsp) != 1:
            msg = ('Failed to find volume id %s' if rsp is None else
                   'Failed to find unique volume id %s')
            LOG.error(msg, volume_uuid)
            raise exc.VolumeBackendAPIException(data=msg % volume_uuid)
        return rsp[0]

    @cinder_utils.trace
    def _find_volume_snap_by_uuid(self, parent_vol_id, snap_uuid):
        rsp = self._api_proxy.find_volsnap_by_uuid(parent_vol_id, snap_uuid)
        if rsp is None or len(rsp) != 1:
            msg = ('Failed to find volume snapshot id %s' if rsp is None else
                   'Failed to find unique volume snapshot id %s')
            LOG.error(msg, snap_uuid)
            raise exc.VolumeBackendAPIException(data=(msg % snap_uuid))
        return rsp[0]

    def _check_cg_supported(self):
        self._load_swversion()
        if self._swversion and self._swversion < MIN_CG_VERSION:
            msg = ('Vexata array version does not support consistency '
                   'groups.')
            LOG.error(msg)
            raise exc.VolumeBackendAPIException(data=msg)

    @cinder_utils.trace
    def do_setup(self, context):
        """Setup the Cinder volume driver.

        """
        self._api_proxy = api_proxy.VexataAPIProxy(
            mgmt_ip=self.configuration.san_ip,
            mgmt_user=self.configuration.san_login,
            mgmt_passwd=self.configuration.san_password,
            mgmt_port=self.configuration.vexata_https_port,
            verify_cert=self.configuration.driver_ssl_cert_verify,
            cert_path=self.configuration.driver_ssl_cert_path)

    @cinder_utils.trace
    def check_for_setup_error(self):
        """Validate that there are no issues with driver config.

        """
        self._load_swversion()

    @cinder_utils.trace
    def get_volume_stats(self, refresh=False):
        if refresh:
            # refresh periodically as array sw can be updated
            self._load_swversion()
            # @TODO(sandeep): api should raise appropriate exception
            try:
                sa_info = self._api_proxy.sa_info()
            except exc.VolumeBackendAPIException:
                raise
            tot_cap_GiB = sa_info['totalCapacity'] / float(units.Ki)
            free_cap_GiB = ((sa_info['totalCapacity'] -
                             sa_info['usedCapacity']) / float(units.Ki))
            prov_cap_GiB = sa_info['provisionedCapacity'] / float(units.Ki)
            op_ratio = sa_info['maxOverProvisioningFactor'] / 100.0
            num_vols = sa_info['entityCounts']['volumeCount']
            data = dict(
                # Required
                volume_backend_name=self._backend_name,
                vendor_name='Vexata',
                driver_version=self.VERSION,
                storage_protocol=self._storage_protocol,
                total_capacity_gb=tot_cap_GiB,
                free_capacity_gb=free_cap_GiB,
                # Optional
                reserved_percentage=0,
                QoS_support=False,
                provisioned_capacity_gb=prov_cap_GiB,
                max_over_subscription_ratio=op_ratio,
                thin_provisioning_support=True,
                thick_provisioning_support=False,
                total_volumes=num_vols,
                multiattach=False
            )
            self._array_info = data
        return self._array_info

    @cinder_utils.trace
    def create_volume(self, volume):
        try:
            self._api_proxy.create_volume(
                self.make_volume_name(volume),
                self.make_volume_desc(volume),
                volume.size * units.Ki,
                volume.id)
        except exc.VolumeBackendAPIException:
            raise

    @cinder_utils.trace
    def extend_volume(self, volume, new_size):
        # TODO(sandeep): Will fail if volume ever had snapshots.
        try:
            vx_vol = self._find_volume_by_uuid(volume.id)
            new_size_MiB = new_size * units.Ki
            if new_size_MiB <= vx_vol['volSize']:
                msg = 'New size should be greater than current size'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)
            orig_vol_id = vx_vol['id']
            orig_vol_name = self.make_volume_name(volume)
            orig_vol_desc = self.make_volume_desc(volume)
            self._api_proxy.grow_volume(orig_vol_name,
                                        orig_vol_desc,
                                        orig_vol_id,
                                        new_size_MiB)
        except exc.VolumeBackendAPIException:
            raise

    @cinder_utils.trace
    def delete_volume(self, volume):
        # TODO(sandeep): if array up and volume already deleted return success
        #       (API returns 404, text='Volume not present')
        try:
            vx_vol = self._find_volume_by_uuid(volume.id)
        except exc.VolumeBackendAPIException:
            raise
        snaps = vx_vol['numOfSnapshots']
        if snaps > 0:
            msg = 'Cannot delete volume %(uuid)s, it has %(snaps)d snapshots'
            msgd = {'uuid': volume.id, 'snaps': snaps}
            LOG.error(msg, msgd)
            raise exc.VolumeIsBusy(volume_name=volume.id)
        try:
            vol_id = vx_vol['id']
            self._api_proxy.delete_volume(vol_id)
        except exc.VolumeBackendAPIException:
            raise

    @cinder_utils.trace
    def create_snapshot(self, snapshot):
        try:
            parent_vol = snapshot.volume
            vx_vol = self._find_volume_by_uuid(parent_vol.id)
            parent_vol_id = vx_vol['id']
        except exc.VolumeBackendAPIException:
            raise
        rsp = self._api_proxy.create_volsnap(
            parent_vol_id,
            self.make_snap_name(snapshot),
            self.make_snap_desc(snapshot),
            snapshot.id)
        if rsp is None:
            msg = 'Failed to create snapshot %(snp)s from volume %(vol)s'
            msgd = {'vol': parent_vol.id, 'snp': snapshot.id}
            LOG.error(msg, msgd)
            raise exc.VolumeBackendAPIException(data=msg % msgd)

    @cinder_utils.trace
    def delete_snapshot(self, snapshot):
        try:
            parent_vol = snapshot.volume
            vx_vol = self._find_volume_by_uuid(parent_vol.id)
            vol_id = vx_vol['id']
            vx_snap = self._find_volume_snap_by_uuid(vol_id, snapshot.id)
            snap_id = vx_snap['id']
        except exc.VolumeBackendAPIException:
            raise
        if not self._api_proxy.delete_volsnap(vol_id, snap_id):
            msg = 'Failed to delete snapshot %(snp)s of volume %(vol)s'
            msgd = {'vol': parent_vol.id, 'snp': snapshot.id}
            LOG.error(msg, msgd)
            raise exc.VolumeBackendAPIException(data=msg % msgd)

    @cinder_utils.trace
    def revert_to_snapshot(self, context, volume, snapshot):
        assert snapshot.volume == volume
        try:
            parent_vol = volume
            vx_vol = self._find_volume_by_uuid(parent_vol.id)
            vol_id = vx_vol['id']
            vx_snap = self._find_volume_snap_by_uuid(vol_id, snapshot.id)
            snap_id = vx_snap['id']
        except exc.VolumeBackendAPIException:
            raise
        # On success returns an empty dict
        rsp = self._api_proxy.restore_volume_from_volsnap(vol_id, snap_id)
        if rsp is None:
            msg = 'Failed to revert volume %(vol)s to snapshot %(snp)s'
            msgd = {'vol': parent_vol.id, 'snp': snapshot.id}
            LOG.error(msg, msgd)
            raise exc.VolumeBackendAPIException(data=msg % msgd)

    @cinder_utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        # may need to expand the cloned volume: volume.size * units.Ki,
        assert volume.size >= snapshot.volume.size
        try:
            parent_vol = snapshot.volume
            vx_vol = self._find_volume_by_uuid(parent_vol.id)
            vol_id = vx_vol['id']
            new_size_MiB = volume.size * units.Ki
            orig_size_MiB = vx_vol['volSize']
            if new_size_MiB < orig_size_MiB:
                msg = 'New size should be greater or equal to current size'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)
            # Increased size not supported on backend
            if new_size_MiB > orig_size_MiB:
                msg = 'Increased clone size not currently supported'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)
            vx_snap = self._find_volume_snap_by_uuid(vol_id, snapshot.id)
            snap_id = vx_snap['id']
            rsp = self._api_proxy.clone_volsnap_to_new_volume(
                snap_id,
                self.make_volume_name(volume),
                self.make_volume_desc(volume),
                volume.id)
            assert volume.id == rsp['voluuid']
            if new_size_MiB > orig_size_MiB:
                self._api_proxy.grow_volume(rsp['name'],
                                            rsp['description'],
                                            rsp['voluuid'],
                                            new_size_MiB)
        except exc.VolumeBackendAPIException:
            raise

    @cinder_utils.trace
    def create_cloned_volume(self, volume, src_vref):
        assert volume.size >= src_vref['size']
        try:
            vx_vol = self._find_volume_by_uuid(src_vref['id'])
            vol_id = vx_vol['id']
            new_size_MiB = volume.size * units.Ki
            orig_size_MiB = vx_vol['volSize']
            if new_size_MiB < orig_size_MiB:
                msg = 'New size should be greater or equal to current size'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)
            # Increased size not supported on backend
            if new_size_MiB > orig_size_MiB:
                msg = 'Increased clone size not currently supported'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)
            # Create a temporary snapshot
            temp_uuid = str(uuid.uuid4())
            vx_snap = self._api_proxy.create_volsnap(
                vol_id,
                self._make_label(temp_uuid, CNDR_SNPNAME, MAX_NAME_LEN),
                self._make_label(temp_uuid, CNDR_SNPDESC, MAX_DESC_LEN),
                temp_uuid)
            snap_id = vx_snap['id']
            rsp = self._api_proxy.clone_volsnap_to_new_volume(
                snap_id,
                self.make_volume_name(volume),
                self.make_volume_desc(volume),
                volume.id)
            self._api_proxy.delete_volsnap(vol_id, snap_id)
            # grow new volume if required
            assert volume.id == rsp['voluuid']
            if new_size_MiB > orig_size_MiB:
                self._api_proxy.grow_volume(rsp['name'],
                                            rsp['description'],
                                            rsp['voluuid'],
                                            new_size_MiB)
        except exc.VolumeBackendAPIException:
            raise

    # -----------------------------------------------------------------
    # CG: Consistency Groups
    # -----------------------------------------------------------------
    @cinder_utils.trace
    def create_consistencygroup(self, context, group):
        self._check_cg_supported()
        model_update = {'status': fields.GroupStatus.AVAILABLE}
        return model_update

    @cinder_utils.trace
    def delete_consistencygroup(self, context, group, volumes):
        self._check_cg_supported()
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        cg_name = self.make_cg_name(group)
        try:
            vg = self._find_vg_by_name(cg_name)
        except VgNotFoundException:
            # vg is already deleted on the array ?
            vg = None
        except MultipleVgsMatchedException:
            return model_update_err, None

        model_update = model_update_ok
        if vg:
            if vg['exportGroups']:
                LOG.error('CG %s is member of an EG, need to '
                          'delete the EG first.', group.id)
                return model_update_err, None
            if not self._api_proxy.delete_vg(vg['id']):
                model_update = model_update_err

        if not volumes:
            return model_update, None
        # Force delete volumes that used to be in the VG, the CG is already
        # removed from the
        vxvols = self._find_volumes(volumes, vxid_only=False)
        if not vxvols:
            # all the volumes were already deleted independently ?
            msg = 'Did not find any cg volumes on the array, nothing to do'
            LOG.warning(msg)
            return model_update_ok, None
        elif len(vxvols) != len(volumes):
            LOG.error('Did not find all cg volumes %(vol_uuids)s, '
                      'found only the following ids %(vol_ids)s',
                      {'vol_uuids': [vol.id for vol in volumes],
                       'vol_ids': [vol['id'] for vol in vxvols]})
            return model_update_err, None
        volumes_model_update = []
        for vol in vxvols:
            status = {
                'id': vol['voluuid'],
                'status': fields.GroupStatus.DELETED
            }
            # vg deleted previously so it's absent from this volume's vgs
            if vol['volumeGroups']:
                LOG.error('Volume %s is present in another VG/CG, '
                          'cannot delete it.', vol['voluuid'])
                status['status'] = fields.GroupStatus.ERROR_DELETING
            elif not self._api_proxy.delete_volume(vol['id']):
                LOG.error('Delete of volume %d failed.', vol['id'])
                status['status'] = fields.GroupStatus.ERROR_DELETING
            volumes_model_update.append(status)
        return model_update, volumes_model_update

    @cinder_utils.trace
    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        self._check_cg_supported()
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        add_vols_updt = [{'id': vol.id} for vol in add_volumes]
        rmv_volums_updt = [{'id': vol.id} for vol in remove_volumes]
        if len(add_volumes) == 0 and len(remove_volumes) == 0:
            LOG.warning('Empty update for %s, ignoring', group.id)
            return model_update_ok, None, None

        cg_name = self.make_cg_name(group)
        add_vol_ids, rm_vol_ids = [], []
        if add_volumes:
            add_vol_ids = self._find_volumes(add_volumes, vxid_only=True)
            if len(add_vol_ids) != len(add_volumes):
                # Didn't find at least one of the volumes
                return model_update_err, None, None
        if remove_volumes:
            rm_vol_ids = self._find_volumes(remove_volumes, vxid_only=True)
            if len(rm_vol_ids) != len(remove_volumes):
                # Didn't find at least one of the volumes
                return model_update_err, None, None
        try:
            # could be lazy create, don't flag a missing vg right away
            vg = self._find_vg_by_name(cg_name, err_missing=False)
        except VgNotFoundException:
            if rm_vol_ids and len(rm_vol_ids) > 0:
                # vg deleted externally since attempting to remove its volumes
                LOG.error('Unable to find vg for cg %s', group.id)
                return model_update_err, None, None
            else:
                # Only adding volumes, create the vg now
                vg = self._api_proxy.create_vg(cg_name,
                                               self.make_cg_desc(group),
                                               add_vol_ids)
                if not vg:
                    return model_update_err, None, None
                else:
                    return model_update_ok, add_vols_updt, rmv_volums_updt
        except MultipleVgsMatchedException:
            return model_update_err, None, None
        # Existing vg, actual update
        rsp = self._api_proxy.modify_vg(
            vg['id'],
            vg['name'],
            vg['description'],
            add_vol_ids=add_vol_ids,
            rm_vol_ids=rm_vol_ids)
        if rsp:
            return model_update_ok, add_vols_updt, rmv_volums_updt
        else:
            return model_update_err, None, None

    @cinder_utils.trace
    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        self._check_cg_supported()
        # backend will auto name/uuid the individual volume snapshots
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        cg_name = self.make_cg_name(cgsnapshot.group)
        try:
            vg = self._find_vg_by_name(cg_name)
        except VgNotFoundException:
            return model_update_err, None
        except MultipleVgsMatchedException:
            return model_update_err, None
        rsp = self._api_proxy.create_vgsnap(
            vg['id'],
            self.make_cgsnap_name(cgsnapshot),
            self.make_cgsnap_desc(cgsnapshot))
        if rsp:
            return model_update_ok, None
        else:
            return model_update_err, None

    @cinder_utils.trace
    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        self._check_cg_supported()
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        cg_name = self.make_cg_name(cgsnapshot.group)
        cgsnap_name = self.make_cgsnap_name(cgsnapshot)
        try:
            vg = self._find_vg_by_name(cg_name)
        except VgNotFoundException:
            return model_update_err, None
        except MultipleVgsMatchedException:
            return model_update_err, None
        vg_id = vg['id']
        try:
            vgsnap = self._find_vgsnap_by_name(vg_id, cgsnap_name)
        except VgsnapNotFoundException:
            return model_update_err, None
        except MultipleVgsnapsMatchedException:
            return model_update_err, None
        ok = self._api_proxy.delete_vgsnap(vg_id, vgsnap['id'])
        if ok:
            return model_update_ok, None
        else:
            return model_update_err, None

    @cinder_utils.trace
    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistencygroup from source.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        :returns: model_update, volumes_model_update

        The source can be cgsnapshot or a source cg.

        param volumes is retrieved directly from the db. It is a list of
        cinder.db.sqlalchemy.models.Volume to be precise. It cannot be
        assigned to volumes_model_update. volumes_model_update is a list of
        dictionaries. It has to be built by the driver. An entry will be
        in this format: {'id': xxx, 'status': xxx, ......}. model_update
        will be in this format: {'status': xxx, ......}.

        To be consistent with other volume operations, the manager will
        assume the operation is successful if no exception is thrown by
        the driver. For a successful operation, the driver can either build
        the model_update and volumes_model_update and return them or
        return None, None.
        """
        self._check_cg_supported()
        if source_cg:
            return self._clone_cg_from_cg(group, volumes, source_cg)
        elif cgsnapshot and snapshots:
            return self._create_cg_from_cgsnap(group, volumes, cgsnapshot)
        return {'status': fields.GroupStatus.ERROR}, None

    def _clone_cg_from_cg(self, group, volumes, source_cg):
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        # Find the existing VG
        cg_name = self.make_cg_name(source_cg)
        try:
            vg = self._find_vg_by_name(cg_name)
        except VgNotFoundException:
            return model_update_err, None
        except MultipleVgsMatchedException:
            return model_update_err, None
        vg_id = vg['id']

        # Create a temporary vg snapshot
        temp_uuid = str(uuid.uuid4())
        vgsnap = self._api_proxy.create_vgsnap(
            vg_id,
            self._make_label(temp_uuid, CNDR_CGSNAPNAME, MAX_NAME_LEN),
            self._make_label(temp_uuid, CNDR_CGSNAPDESC, MAX_DESC_LEN))
        if not vgsnap:
            LOG.error('Failed to create transient snapshot for vg %d', vg_id)
            return model_update_err, None

        try:
            newvg = self._api_proxy.clone_vgsnap_to_new_vg(
                vgsnap['id'],
                self.make_cg_name(group),
                self.make_cg_desc(group))
            if newvg:
                return model_update_ok, [
                    {'id': vol.id, 'status': fields.GroupStatus.AVAILABLE}
                    for vol in volumes]
            else:
                LOG.error('Failed to clone from transient vg snapshot %d',
                          vgsnap['id'])
                return model_update_err, None
        finally:
            rsp = self._api_proxy.delete_vgsnap(vg_id, vgsnap['id'])
            if not rsp:
                LOG.error('Failed to delete transient vg snapshot %d',
                          vgsnap['id'])

    def _create_cg_from_cgsnap(self, group, volumes, cgsnapshot):
        model_update_ok = {'status': fields.GroupStatus.AVAILABLE}
        model_update_err = {'status': fields.GroupStatus.ERROR}
        # Find the existing VG and its matching SG
        cg_name = self.make_cg_name(cgsnapshot.group)
        cgsnap_name = self.make_cgsnap_name(cgsnapshot)
        try:
            vg = self._find_vg_by_name(cg_name)
        except VgNotFoundException:
            return model_update_err, None
        except MultipleVgsMatchedException:
            return model_update_err, None
        vg_id = vg['id']
        try:
            vgsnap = self._find_vgsnap_by_name(vg_id, cgsnap_name)
        except VgsnapNotFoundException:
            return model_update_err, None
        except MultipleVgsnapsMatchedException:
            return model_update_err, None

        rsp = self._api_proxy.clone_vgsnap_to_new_vg(
            vgsnap['id'],
            self.make_cg_name(group),
            self.make_cg_desc(group))
        if rsp:
            return model_update_ok, [
                {'id': vol.id, 'status': fields.GroupStatus.AVAILABLE}
                for vol in volumes]
        else:
            LOG.error('Failed to clone vg snapshot id %s',
                      vgsnap['id'])
            return model_update_err, None

    # -----------------------------------------------------------------
    # GVG: Generic Volume Groups
    #  Only supports the consistency group functionality for now.
    # -----------------------------------------------------------------
    def create_group(self, context, group):
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self.create_consistencygroup(context, group)
        raise NotImplementedError()

    def delete_group(self, context, group, volumes):
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self.delete_consistencygroup(context, group, volumes)
        raise NotImplementedError()

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self.update_consistencygroup(
                context, group,
                add_volumes, remove_volumes)
        raise NotImplementedError()

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self.create_consistencygroup_from_src(
                context, group, volumes,
                group_snapshot, snapshots,
                source_group, source_vols)
        raise NotImplementedError()

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        if vol_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self.create_cgsnapshot(context, group_snapshot, snapshots)
        raise NotImplementedError()

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        if vol_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self.delete_cgsnapshot(context, group_snapshot, snapshots)
        raise NotImplementedError()


@interface.volumedriver
class VexataVX100FibreChannelDriver(VexataVX100BaseDriver,
                                    driver.FibreChannelDriver):
    """Vexata VX100 FibreChannel volume driver.

    """
    def __init__(self, *args, **kwargs):
        super(VexataVX100FibreChannelDriver, self).__init__(*args, **kwargs)
        self._storage_protocol = "FC"
        self._lookup_service = fczm_utils.create_lookup_service()

    def create_export(self, context, volume, connector):
        initiator_wwns = connector['wwpns']
        target_wwns = self._get_target_wwns()
        ok = self._export_volumes([volume], initiator_wwns, target_wwns)
        if not ok:
            # TODO(sandeep): raise error ?
            raise Exception('Create export failed')
        return None

    def initialize_connection(self, volume, connector):
        """Attaches volume to an instance

        """
        cfg = configuration.Configuration(manager.volume_manager_opts)
        zm = cfg.safe_get('zoning_mode')
        LOG.debug('ZONING MODE=%s', zm)
        if zm and zm == 'fabric':
            # TODO(sandeep): Need lun id before zone, I-T nexus creation.
            tgt_lun = 1
        else:
            # pre-zoned
            tgt_lun = self._find_lun_id(volume, connector['wwpns'])
            if not tgt_lun:
                msg = 'Unable to find target lun mapping'
                LOG.error(msg)
                raise exc.VolumeBackendAPIException(data=msg)

        target_wwns = self._get_target_wwns()
        init_targ_map = self._build_initiator_target_map(
            target_wwns, connector)
        data = {
            'driver_volume_type': 'fibre_channel',
            'data': {
                'target_lun': tgt_lun,
                'target_discovered': True,
                'target_wwn': target_wwns,
                'initiator_target_map': init_targ_map,
            }
        }
        fczm_utils.add_fc_zone(data)
        return data

    def terminate_connection(self, volume, connector, **kwargs):
        """Detach volume from an instance.

        connector may be None => force detach volume
        kwargs can be 'force'
        """
        data = {
            'driver_volume_type': 'fibre_channel',
            'data': {}
        }
        if connector:
            force = False
            initiator_wwns = connector['wwpns']
        else:
            force = True
            initiator_wwns = None
        target_wwns = self._get_target_wwns()
        ok, more_mappings = self._unexport_volumes(
            [volume], initiator_wwns, target_wwns, force
        )
        if not ok:
            # TODO(sandeep): raise error ?
            return None

        if not more_mappings:
            init_targ_map = self._build_initiator_target_map(
                target_wwns, connector)
            data['data'] = {
                'target_wwn': target_wwns,
                'initiator_target_map': init_targ_map,
            }

        fczm_utils.remove_fc_zone(data)
        return data

    @cinder_utils.trace
    def _build_initiator_target_map(self, target_wwns, connector):
        """Build the initiator target map.

        """
        init_targ_map = {}
        initiator_wwns = connector['wwpns']
        if self._lookup_service:
            # Use FC nameserver to lookup all the initiator and target
            # WWNs are logged in on each fabric.
            dev_map = self._lookup_service.get_device_mapping_from_network(
                initiator_wwns, target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
        else:
            # No lookup service
            init_targ_map = dict.fromkeys(connector['wwpns'], target_wwns)
        return init_targ_map

    @cinder_utils.trace
    def _get_target_wwns(self, online_only=False):
        saports = self._api_proxy.list_saports()
        if online_only:
            return [vx2cinder_wwn(port['name']) for port in saports
                    if port['state'] == 'ONLINE']
        else:
            return [vx2cinder_wwn(port['name']) for port in saports]

    @cinder_utils.trace
    def _export_volumes(self, cndr_volumes, initiator_wwns, target_wwns):
        """Make volumes visible to initiators.

        """
        saport_ids = self._find_saports(target_wwns)
        if saport_ids is None:
            # TODO(sandeep): raise error ? One or more saports is not found
            return False
        vol_ids = self._find_volumes(cndr_volumes, vxid_only=True)
        if len(vol_ids) != len(cndr_volumes):
            # TODO(sandeep): raise error ? One or more volumes was not found
            return False

        created_ig_or_pg = False
        ini_ids = self._find_initiators(initiator_wwns, create_missing=True)
        igs = self._find_igs(ini_ids)
        if not igs:
            created_ig_or_pg = True
            igs = [self._create_ig(ini_ids)]
        pgs = self._find_pgs(saport_ids)
        if not pgs:
            created_ig_or_pg = True
            pgs = [self._create_pg(saport_ids)]

        # vgs containing only these volumes
        vgs = self._find_vgs(vol_ids)
        if not created_ig_or_pg:
            # Any existing egs mapping any of the igs + pgs ?
            egs = self._find_egs_with_igs_pgs(igs, pgs)
            # existing egs already have vg containing the volume(s) ?
            matched_vgs = self._get_vgs_in_egs(vgs, egs)
            if matched_vgs:
                # The volume(s) are already exported
                LOG.debug('Volume(s) are already exported from array')
                return True
            elif egs:
                # Pick an eg that will have a vg and add volumes to it
                if self._add_vols_to_eg_vg(egs[0], vol_ids):
                    return True
                return False
            else:
                # Create a vg and eg
                new_vg = self._create_vg(vol_ids)
                vg_id = new_vg['id']
        else:
            # ig or pg was created => eg must be created
            if vgs:
                vg_id = vgs[0]['id']
            else:
                new_vg = self._create_vg(vol_ids)
                vg_id = new_vg['id']
        ig_id = igs[0]['id']
        pg_id = pgs[0]['id']
        new_eg = self._create_eg(vg_id, ig_id, pg_id)
        if new_eg:
            LOG.debug('Exported volume(s) from array')
            return True
        else:
            LOG.debug('Exporting volume(s) from array failed')
            return False

    @cinder_utils.trace
    def _unexport_volumes(self, cndr_volumes, initiator_wwns,
                          target_wwns, force):
        """Remove visibility of volumes seen by the initiator.

        Returns (success, more_mappings).
        If more_mappings the switch zoning should not be cleaned up when
        using zonemanager.
        """
        saport_ids = self._find_saports(target_wwns)
        if saport_ids is None:
            # TODO(sandeep): raise error ? One or more saports is not found
            return False, None
        vol_ids = self._find_volumes(cndr_volumes, vxid_only=True)
        if len(vol_ids) != len(cndr_volumes):
            # TODO(sandeep): raise error ? One or more volumes was not found
            return False, None

        # vgs containing only these volumes
        vgs = self._find_vgs(vol_ids)
        pgs = self._find_pgs(saport_ids)
        # initiator_wwns will be None for a force detach.
        if force:
            # force detach, consider all egs from targets
            egs = self._find_egs_with_pgs(pgs)
        else:
            ini_ids = self._find_initiators(
                initiator_wwns, create_missing=False)
            if ini_ids is None:
                # Raise error ? One or more initiators was not found
                return False, None
            igs = self._find_igs(ini_ids)
            # egs that are exposing volumes between initators and targets
            egs = self._find_egs_with_igs_pgs(igs, pgs)

        success = True
        deleted_egids = set()
        vg_id_set = frozenset(vg['id'] for vg in vgs)
        for eg in egs:
            eg_id = eg['id']
            eg_vg_id = eg['exportGroup3Tuple']['vgId']
            if eg_vg_id in vg_id_set:
                # eg with vg having these volumes only, can delete vg and eg
                ok = self._api_proxy.delete_eg(eg_id)
                if not ok:
                    LOG.error('Failed to delete eg %d', eg_id)
                    success = False
                else:
                    deleted_egids.add(eg_id)
                    LOG.debug('Deleted eg %d', eg_id)
                ok = self._api_proxy.delete_vg(eg_vg_id)
                if not ok:
                    LOG.error('Failed to delete vg %d', eg_vg_id)
                    success = False
                else:
                    LOG.debug('Deleted vg %d', eg_vg_id)
            else:
                reqd_vol_id_set = frozenset(vol_ids)
                # vg of this eg may or may not contain these volumes
                vg = self._api_proxy.find_vg_by_id(eg_vg_id)
                vg_vol_ids = frozenset(vg['currVolumes'])
                if vg_vol_ids.issuperset(reqd_vol_id_set):
                    vg_id = vg['id']
                    rsp = self._api_proxy.modify_vg(
                        vg_id,
                        vg['name'],
                        vg['description'],
                        add_vol_ids=[],
                        rm_vol_ids=vol_ids
                    )
                    if rsp is None:
                        LOG.error('Failed to remove volumes %(vols)s '
                                  'from vg %(id)d',
                                  {'vols': vol_ids, 'id': vg_id})
                        success = False
                    else:
                        LOG.debug('Removed volumes %(vols)s from vg %(id)d',
                                  {'vols': vol_ids, 'id': vg_id})

        # egs with the same [ig,]pg may exist with some other volumes
        # if so, we should not destroy any zones yet.
        more_mappings = len(egs) > len(deleted_egids)
        return success, more_mappings

    @cinder_utils.trace
    def _find_lun_id(self, cndr_vol, initiator_wwns):
        # Will not work with dynamic zoning
        # Only applicable for pre-zoned switches where initiator can login
        # to the array at which time the lun mapping is created today.
        # Need to only return a single lun id for attach logic to work.
        vol_ids = self._find_volumes([cndr_vol], vxid_only=True)
        if not vol_ids:
            return None
        vol_id = vol_ids[0]
        # A single initiator is enough
        ini_wwn = initiator_wwns[0]
        ini_ids = self._find_initiators([ini_wwn], create_missing=False)
        if not ini_ids:
            return None
        ini_id = ini_ids[0]
        # Find all ports that are online
        saports = self._api_proxy.list_saports()
        saport_ids = [port['id'] for port in saports
                      if port['state'] == 'ONLINE']
        # Find the first lun mapping if it exists
        for saport_id in saport_ids:
            itns = self._api_proxy.list_lun_mappings(ini_id, saport_id)
            if not itns:
                continue
            for itn in itns:
                mappings = itn['volumeMappings']
                for m in mappings:
                    if m['volumeId'] == vol_id:
                        lun_id = m['hostLunId']
                        LOG.debug('Found lun id %(lun_id)d for volume '
                                  '%(vol_id)d, initiator %(ini_id)d, '
                                  'saport %(saport_id)d',
                                  {'lun_id': lun_id, 'vol_id': vol_id,
                                   'ini_id': ini_id, 'saport_id': saport_id})
                        return lun_id

        LOG.error('Failed to find lun mapping for volume %(vol_id)d '
                  'from initiator %(ini_id)d',
                  {'vol_id': vol_id, 'ini_id': ini_id})
        return None
