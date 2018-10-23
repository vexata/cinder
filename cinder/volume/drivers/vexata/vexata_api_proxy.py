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
Vexata REST API proxy.

"""

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class VexataAPIProxy(object):
    NODE_ID = 0
    SA_ID = 0
    DUMMY_SIZE = 1
    # API succcess codes
    DELETE_OK = 204
    GET_OK = 200
    POST_OK = 201
    POST_OK_204 = 204
    PUT_OK = 200

    def __init__(self,
                 mgmt_ip,
                 mgmt_user,
                 mgmt_passwd,
                 mgmt_port=None,
                 verify_cert=True,
                 cert_path=None):
        """Init method.

        :param mgmt_ip: Hostname or IP of the Vexata array
        :param mgmt_user: Array management username
        :param mgmt_passwd: Array management password
        :param mgmt_port: HTTPS port, None to use default (443)
        :param verify_cert: Whether to verify certificates for HTTPS
        :param cert_path: Directory where certificates may be found
        """
        # TODO(sandeep): timeout for requests
        self.ip = mgmt_ip
        self.user = mgmt_user
        self.passwd = mgmt_passwd
        self.port = mgmt_port
        self.verify_cert = verify_cert
        self.cert_path = cert_path

    def _url(self, uri):
        port = ':%d' % self.port if self.port is not None else ''
        return ('https://%(ip)s%(port)s%(uri)s'
                % {'ip': self.ip, 'port': port, 'uri': uri})

    def _request(self, method, uri, data=None):
        assert method in ('GET', 'POST', 'PUT', 'DELETE')
        if self.verify_cert:
            verify = self.cert_path or True
        else:
            verify = False
        if method == 'GET':
            rsp = requests.request(method,
                                   self._url(uri),
                                   params=data,
                                   auth=(self.user, self.passwd),
                                   verify=verify)
        else:
            rsp = requests.request(method,
                                   self._url(uri),
                                   json=data,
                                   auth=(self.user, self.passwd),
                                   verify=verify)
        return rsp

    def _get(self, uri, data=None, exp_rsp_code=None):
        rsp = self._request('GET', uri, data)
        rsp_code = exp_rsp_code or self.GET_OK
        if rsp.status_code != rsp_code:
            # TODO(sandeep): raise exception
            return None
        return rsp.json()

    def _post(self, uri, data, exp_rsp_code=None):
        rsp = self._request('POST', uri, data=data)
        rsp_code = exp_rsp_code or self.POST_OK
        if rsp.status_code != rsp_code:
            # TODO(sandeep): raise exception
            return None
        if exp_rsp_code == self.POST_OK_204:
            # No response body
            return {}
        else:
            return rsp.json()

    def _put(self, uri, data, exp_rsp_code=None):
        rsp = self._request('PUT', uri, data=data)
        rsp_code = exp_rsp_code or self.PUT_OK
        if rsp.status_code != rsp_code:
            # TODO(sandeep): raise exception
            return None
        return rsp.json()

    def _delete(self, uri, exp_rsp_code=None):
        rsp = self._request('DELETE', uri)
        rsp_code = exp_rsp_code or self.DELETE_OK
        if rsp.status_code != rsp_code:
            # TODO(sandeep): raise exception
            return False
        return True

    def test_connection(self):
        uri = '/api/mgmtping'
        return self._get(uri) is not None

    def iocs(self):
        uri = ('/api/nodes/%(node_id)d/iocs'
               % {'node_id': self.NODE_ID})
        return self._get(uri)

    def sa_info(self):
        uri = ('/api/storagearrays/%(sa_id)d'
               % {'sa_id': self.SA_ID})
        return self._get(uri)

    # -----------------------------------------------------------------
    # Volumes
    # -----------------------------------------------------------------
    def list_volumes(self):
        uri = ('/api/storagearrays/%(sa_id)d/volumes'
               % {'sa_id': self.SA_ID})
        return self._get(uri)


    def find_volume_by_uuid(self,
                            volume_uuid):
        uri = ('/api/storagearrays/%(sa_id)d/volumes'
               % {'sa_id': self.SA_ID})
        data = {'uuid': volume_uuid}
        # returns a list of volumes, ideally singleton
        return self._get(uri, data)

    def create_volume(self,
                      vol_name,
                      vol_desc,
                      vol_size_MiB,
                      vol_uuid=None):
        uri = ('/api/storagearrays/%(sa_id)d/volumes'
               % {'sa_id': self.SA_ID})
        data = {
            'name': vol_name,
            'volSize': vol_size_MiB,
            'description': vol_desc,
        }
        if vol_uuid:
            data['voluuid'] = vol_uuid
        return self._post(uri, data)

    def grow_volume(self,
                    orig_vol_name,
                    orig_vol_desc,
                    orig_vol_id,
                    new_size_MiB):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d'
               % {'sa_id': self.SA_ID, 'vol_id': orig_vol_id})
        data = {
            'name': orig_vol_name,
            'description': orig_vol_desc,
            'volSize': new_size_MiB,
        }
        return self._put(uri, data)

    def delete_volume(self,
                      vol_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d'
               % {'sa_id': self.SA_ID, 'vol_id': vol_id})
        return self._delete(uri)

    # -----------------------------------------------------------------
    # Volume Snapshots & Clones
    # -----------------------------------------------------------------
    def list_volsnaps(self, vol_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d'
               '/snapshots'
               % {'sa_id': self.SA_ID, 'vol_id': vol_id})
        # returns [{"id": 72, "parentVolumeId": 64, "snapshot": true, ...}, ...]
        return self._get(uri)

    def find_volsnap_by_uuid(self,
                             parent_vol_id,
                             snap_uuid):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d/snapshots'
               % {'sa_id': self.SA_ID, 'vol_id': parent_vol_id})
        rsp = self._get(uri)
        if rsp is None:
            return None
        # REST API does not support request filtered by snap UUID.
        matches = filter(lambda snap: snap['voluuid'] == snap_uuid, rsp)
        # returns a list of snaps, ideally singleton
        return matches

    def create_volsnap(self,
                       parent_vol_id,
                       snap_name,
                       snap_desc,
                       snap_uuid=None):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d/snapshots'
               % {'sa_id': self.SA_ID, 'vol_id': parent_vol_id})
        data = {
            'name': snap_name,
            'description': snap_desc,
            'volSize': self.DUMMY_SIZE,  # api bug ? should not be required
        }
        if snap_uuid:
            data['voluuid'] = snap_uuid
        return self._post(uri, data)

    def delete_volsnap(self,
                       parent_vol_id,
                       snap_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d'
               '/snapshots/%(snap_id)d'
               % {'sa_id': self.SA_ID, 'vol_id': parent_vol_id,
                  'snap_id': snap_id})
        return self._delete(uri)

    def restore_volume_from_volsnap(self,
                                    parent_vol_id,
                                    snap_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumes/%(vol_id)d'
               '/snapshots/%(snap_id)d/restore'
               % {'sa_id': self.SA_ID, 'vol_id': parent_vol_id,
                  'snap_id': snap_id})
        # on success returns empty dict
        return self._post(uri, data=None, exp_rsp_code=self.POST_OK_204)

    def clone_volsnap_to_new_volume(self,
                                    snap_id,
                                    vol_name,
                                    vol_desc,
                                    vol_uuid=None):
        uri = ('/api/storagearrays/%(sa_id)d/snapshots/%(snap_id)d/clones'
               % {'sa_id': self.SA_ID, 'snap_id': snap_id})
        data = {
            'name': vol_name,
            'description': vol_desc,
        }
        if vol_uuid:
            data['voluuid'] = vol_uuid
        return self._post(uri, data)

    # -----------------------------------------------------------------
    # Initiators
    # -----------------------------------------------------------------
    def list_initiators(self):
        uri = ('/api/storagearrays/%(sa_id)d/initiators'
               % {'sa_id': self.SA_ID})
        # returns [{'id': 0, 'memberId': 'aa:bb:cc:dd:ee:ff:gg:hh',
        #   'initiatorType': 'FC', ... }]
        return self._get(uri)

    def add_initiator(self,
                      ini_name,
                      ini_desc,
                      ini_addr):
        uri = ('/api/storagearrays/%(sa_id)d/initiators'
               % {'sa_id': self.SA_ID})
        # ini_addr: string in hex:colon notation
        data = {
            'name': ini_name,
            'description': ini_desc,
            'memberId': ini_addr,
        }
        return self._post(uri, data)

    def remove_initiator(self,
                         ini_id):
        uri = ('/api/storagearrays/%(sa_id)d/initiators/%(ini_id)d'
               % {'sa_id': self.SA_ID, 'ini_id': ini_id})
        return self._delete(uri)

    # -----------------------------------------------------------------
    # SA Ports
    # -----------------------------------------------------------------
    def list_saports(self):
        uri = ('/api/storagearrays/%(sa_id)d/storagearrayports'
               % {'sa_id': self.SA_ID})
        # Returns [{'id': 0, 'state': 'ONLINE', 'nameType': 'WWN',
        #  'type': 'FIBRECHANNEL', 'name': '00:11:22:33:44:55:66:77',...} ...]
        return self._get(uri)

    # -----------------------------------------------------------------
    # Volume Groups
    # -----------------------------------------------------------------
    def list_vgs(self):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups'
               % {'sa_id': self.SA_ID})
        # returns [{'id': 0, 'name': 'vg_1', 'numOfVols': 3,
        #   'currVolumes': [64, 65, 66], 'exportGroups': [0]..}, ...]
        return self._get(uri)

    def find_vg_by_id(self, vg_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id})
        # returns {'id': 0, 'name': 'vg_1', 'numOfVols': 3,
        #   'currVolumes': [64, 65, 66], 'exportGroups': [0]..}
        return self._get(uri)

    def create_vg(self,
                  vg_name,
                  vg_desc,
                  vol_ids):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups'
               % {'sa_id': self.SA_ID})
        data = {
            'name': vg_name,
            'description': vg_desc,
            'addVolumes': vol_ids,
        }
        return self._post(uri, data)

    def delete_vg(self, vg_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id})
        return self._delete(uri)

    def modify_vg(self,
                  vg_id,
                  vg_name,
                  vg_desc,
                  add_vol_ids,
                  rm_vol_ids):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id})
        data = {
            'name': vg_name,
            'description': vg_desc,
            'addVolumes': add_vol_ids,
            'deleteVolumes': rm_vol_ids,
        }
        return self._put(uri, data)

    # -----------------------------------------------------------------
    # Volume Group Snapshots & Clones
    # -----------------------------------------------------------------
    def list_vgsnaps(self, vg_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               '/snapshots'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id})
        # returns [{'parentVolumeGroupId': 0, 'exportGroups': [],
        #   'currVolumes': [67, 68, 69], 'numOfVols': 3, 'id': 1,
        #   'name': 'vg0_snap1', ...}, ...]
        return self._get(uri)

    def find_vgsnap_by_id(self,
                          vg_id,
                          snap_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               '/snapshots/%(snap_id)d'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id, 'snap_id': snap_id})
        # returns {'parentVolumeGroupId': 0, 'exportGroups': [],
        #   'currVolumes': [67, 68, 69], 'numOfVols': 3, 'id': 1,
        #   'name': 'vg0_snap1', ...}
        return self._get(uri)

    def create_vgsnap(self,
                      vg_id,
                      snap_name,
                      snap_desc):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               '/snapshots'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id})
        data = {
            'name': snap_name,
            'description': snap_desc,
        }
        # {'id': 2,'name': 'vg0_snap2','description': 'test desc',
        # 'numOfVols': 3,'currVolumes': [70,71,72],
        # 'parentVolumeGroupId': 0}
        return self._post(uri, data)

    def delete_vgsnap(self,
                      vg_id,
                      snap_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               '/snapshots/%(snap_id)d'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id, 'snap_id': snap_id})
        return self._delete(uri)

    def restore_vg_from_vgsnap(self,
                               vg_id,
                               snap_id):
        uri = ('/api/storagearrays/%(sa_id)d/volumegroups/%(vg_id)d'
               '/snapshotgroups/%(snap_id)d/restorevolumegroup'
               % {'sa_id': self.SA_ID, 'vg_id': vg_id, 'snap_id': snap_id})
        # on success returns empty dict
        return self._post(uri, data=None, exp_rsp_code=self.POST_OK_204)

    def clone_vgsnap_to_new_vg(self,
                               snap_id,
                               vg_name,
                               vg_desc):
        uri = ('/api/storagearrays/%(sa_id)d/snapshotgroups/%(snap_id)d/clones'
               % {'sa_id': self.SA_ID, 'snap_id': snap_id})
        data = {
            'name': vg_name,
            'description': vg_desc,
        }
        return self._post(uri, data)

    # -----------------------------------------------------------------
    # Initiator Groups
    # -----------------------------------------------------------------
    def list_igs(self):
        uri = ('/api/storagearrays/%(sa_id)d/initiatorgroups'
               % {'sa_id': self.SA_ID})
        # returns [{ 'id': 0, 'name': 'atf_ig_1', 'currInitiators': [2, 3],
        #   'exportGroups': [ 0], ... } ...]
        return self._get(uri)

    def create_ig(self,
                  ig_name,
                  ig_desc,
                  ini_ids,
                  hostprofile=None):
        uri = ('/api/storagearrays/%(sa_id)d/initiatorgroups'
               % {'sa_id': self.SA_ID})
        data = {
            'name': ig_name,
            'description': ig_desc,
            'addInitiators': ini_ids,
        }
        if hostprofile:
            data['hostProfileType'] = hostprofile
        return self._post(uri, data)

    def delete_ig(self,
                  ig_id):
        uri = ('/api/storagearrays/%(sa_id)d/initiatorgroups/%(ig_id)d'
               % {'sa_id': self.SA_ID, 'ig_id': ig_id})
        return self._delete(uri)

    def modify_ig(self,
                  ig_id,
                  ig_name,
                  ig_desc,
                  add_ini_ids,
                  rm_ini_ids):
        uri = ('/api/storagearrays/%(sa_id)d/initiatorgroups/%(ig_id)d'
               % {'sa_id': self.SA_ID, 'ig_id': ig_id})
        data = {
            'name': ig_name,
            'description': ig_desc,
            'addInitiators': add_ini_ids,
            'deleteInitiators': rm_ini_ids,
        }
        return self._put(uri, data)

    # -----------------------------------------------------------------
    # Port Groups
    # -----------------------------------------------------------------
    def list_pgs(self):
        uri = ('/api/storagearrays/%(sa_id)d/portgroups'
               % {'sa_id': self.SA_ID})
        # returns [{'id': 0, 'name': 'pg_1', 'currPorts': [2,3,10,11],
        #   'exportGroups': [0],..} ...]
        return self._get(uri)

    def create_pg(self,
                  pg_name,
                  pg_desc,
                  saport_ids):
        uri = ('/api/storagearrays/%(sa_id)d/portgroups'
               % {'sa_id': self.SA_ID})
        data = {
            'name': pg_name,
            'description': pg_desc,
            'addPorts': saport_ids,
        }
        return self._post(uri, data)

    def delete_pg(self, pg_id):
        uri = ('/api/storagearrays/%(sa_id)d/portgroups/%(pg_id)d'
               % {'sa_id': self.SA_ID, 'pg_id': pg_id})
        return self._delete(uri)

    def modify_pg(self,
                  pg_id,
                  pg_name,
                  pg_desc,
                  add_port_ids,
                  rm_port_ids
                  ):
        uri = ('/api/storagearrays/%(sa_id)d/portgroups/%(pg_id)d'
               % {'sa_id': self.SA_ID, 'pg_id': pg_id})
        data = {
            'name': pg_name,
            'description': pg_desc,
            'addPorts': add_port_ids,
            'deletePorts': rm_port_ids,
        }
        return self._put(uri, data)

    # -----------------------------------------------------------------
    # Export Groups
    # -----------------------------------------------------------------
    def list_egs(self):
        uri = ('/api/storagearrays/%(sa_id)d/exportgroups'
               % {'sa_id': self.SA_ID})
        # returns [{'id': 0, 'name': 'eg_1', 'exportGroup3Tuple':
        #   {'vgId': 0,'igId': 0,'pgId': 0}, ...}, ...]
        return self._get(uri)

    def create_eg(self,
                  eg_name,
                  eg_desc,
                  eg_tuple):
        assert len(eg_tuple) == 3
        uri = ('/api/storagearrays/%(sa_id)d/exportgroups'
               % {'sa_id': self.SA_ID})
        data = {
            'name': eg_name,
            'description': eg_desc,
            'exportGroup3Tuple': {
                'vgId': eg_tuple[0],
                'igId': eg_tuple[1],
                'pgId': eg_tuple[2],
            },
        }
        return self._post(uri, data)

    def delete_eg(self, eg_id):
        uri = ('/api/storagearrays/%(sa_id)d/exportgroups/%(eg_id)d'
               % {'sa_id': self.SA_ID, 'eg_id': eg_id})
        return self._delete(uri)

    def modify_eg(self,
                  eg_id,
                  eg_name,
                  eg_desc,
                  vg_id,
                  ig_id,
                  pg_id):
        uri = ('/api/storagearrays/%(sa_id)d/exportgroups/%(eg_id)d'
               % {'sa_id': self.SA_ID, 'eg_id': eg_id})
        data = {
            'name': eg_name,
            'description': eg_desc,
            'exportGroup3Tuple': {
                'vgId': vg_id,
                'igId': ig_id,
                'pgId': pg_id,
            },
        }
        return self._put(uri, data)

    # -----------------------------------------------------------------
    # LUN Mappings
    # -----------------------------------------------------------------
    def list_lun_mappings(self,
                          ini_id,
                          saport_id):
        uri = ('/api/storagearrays/%(sa_id)d/initiators/%(ini_id)d/'
               'ports/%(saport_id)d'
               % {'sa_id': self.SA_ID, 'saport_id': saport_id,
                  'ini_id': ini_id})
        # returns [{"itnId": 1025, "initiatorWwn": "10:00:00:90:fa:92:72:e4",
        #           "portWwn": "20:02:3c:91:2b:00:73:00",
        #            "volumeMappings": [{ "volumeId": 64, "hostLunId": 1},
        #            {"volumeId": 65, "hostLunId": 2}, ...]}, ...]
        return self._get(uri)
