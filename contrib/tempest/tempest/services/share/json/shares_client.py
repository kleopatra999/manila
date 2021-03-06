# Copyright 2014 Mirantis Inc.
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

import json
import time
import urllib

from tempest.common import rest_client
from tempest.common.utils.data_utils import rand_name
from tempest import config_share as config
from tempest import exceptions
from tempest.exceptions import share_exceptions

CONF = config.CONF


class SharesClient(rest_client.RestClient):
    """Tempest REST client for Manila.

    It handles shares and access to it in OpenStack.
    """

    def __init__(self, auth_provider):
        super(SharesClient, self).__init__(auth_provider)
        self.service = CONF.share.catalog_type
        self.share_protocol = None
        if CONF.share.enable_protocols:
            self.share_protocol = CONF.share.enable_protocols[0]
        self.share_network_id = CONF.share.share_network_id
        self.build_interval = CONF.share.build_interval
        self.build_timeout = CONF.share.build_timeout
        self.auth_params = auth_provider._auth_params()

    def _get_endpoint_type(self, service):
        # This is workaround for rest_client, that uses main config
        return CONF.share.endpoint_type

    def create_share(self, share_protocol=None, size=1,
                     name=None, snapshot_id=None,
                     description="tempest created share",
                     metadata={}, share_network_id=None):
        if name is None:
            name = rand_name("tempest-created-share")
        if share_protocol is None:
            share_protocol = self.share_protocol
        if share_protocol is None:
            raise share_exceptions.ShareProtocolNotSpecified()
        post_body = {
            "share": {
                "share_proto": share_protocol,
                "description": description,
                "snapshot_id": snapshot_id,
                "name": name,
                "size": size,
                "metadata": metadata
            }
        }
        if CONF.share.multitenancy_enabled:
            if share_network_id:
                post_body["share"]["share_network_id"] = share_network_id
            elif self.share_network_id:
                post_body["share"]["share_network_id"] = self.share_network_id
            else:
                raise share_exceptions.ShareNetworkNotSpecified()
        body = json.dumps(post_body)
        resp, body = self.post("shares", body)
        return resp, self._parse_resp(body)

    def delete_share(self, share_id):
        return self.delete("shares/%s" % share_id)

    def list_shares(self):
        resp, body = self.get("shares")
        return resp, self._parse_resp(body)

    def list_shares_with_detail(self, params=None):
        """List the details of all shares."""
        uri = 'shares/detail'
        if params:
                uri += '?%s' % urllib.urlencode(params)
        resp, body = self.get(uri)
        return resp, self._parse_resp(body)

    def get_share(self, share_id):
        resp, body = self.get("shares/%s" % share_id)
        return resp, self._parse_resp(body)

    def create_access_rule(self, share_id,
                           access_type="ip", access_to="0.0.0.0"):
        post_body = {
            "os-allow_access": {
                "access_type": access_type,
                "access_to": access_to
            }
        }
        body = json.dumps(post_body)
        resp, body = self.post("shares/%s/action" % share_id, body)
        return resp, self._parse_resp(body)

    def list_access_rules(self, share_id):
        body = {"os-access_list": None}
        resp, body = self.post("shares/%s/action" % share_id, json.dumps(body))
        return resp, self._parse_resp(body)

    def delete_access_rule(self, share_id, rule_id):
        post_body = {
            "os-deny_access": {
                "access_id": rule_id
            }
        }
        body = json.dumps(post_body)
        return self.post("shares/%s/action" % share_id, body)

    def create_snapshot(self, share_id, name=None,
                        description="tempest created share-ss",
                        force=False):
        if name is None:
            name = rand_name("tempest-created-share-snap")
        post_body = {
            "snapshot": {
                "name": name,
                "force": force,
                "description": description,
                "share_id": share_id
            }
        }
        body = json.dumps(post_body)
        resp, body = self.post("snapshots", body)
        return resp, self._parse_resp(body)

    def get_snapshot(self, snapshot_id):
        resp, body = self.get("snapshots/%s" % snapshot_id)
        return resp, self._parse_resp(body)

    def list_snapshots(self):
        resp, body = self.get("snapshots")
        return resp, self._parse_resp(body)

    def list_snapshots_with_detail(self, params=None):
        """List the details of all shares."""
        uri = 'snapshots/detail'
        if params:
            uri += '?%s' % urllib.urlencode(params)
        resp, body = self.get(uri)
        return resp, self._parse_resp(body)

    def delete_snapshot(self, snap_id):
        return self.delete("snapshots/%s" % snap_id)

    def wait_for_share_status(self, share_id, status):
        """Waits for a Share to reach a given status."""
        resp, body = self.get_share(share_id)
        share_name = body['name']
        share_status = body['status']
        start = int(time.time())

        while share_status != status:
            time.sleep(self.build_interval)
            resp, body = self.get_share(share_id)
            share_status = body['status']
            if 'error' in share_status:
                raise share_exceptions.\
                    ShareBuildErrorException(share_id=share_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Share %s failed to reach %s status within '
                           'the required time (%s s).' %
                           (share_name, status, self.build_timeout))
                raise exceptions.TimeoutException(message)

    def wait_for_snapshot_status(self, snapshot_id, status):
        """Waits for a Share to reach a given status."""
        resp, body = self.get_snapshot(snapshot_id)
        snapshot_name = body['name']
        snapshot_status = body['status']
        start = int(time.time())

        while snapshot_status != status:
            time.sleep(self.build_interval)
            resp, body = self.get_snapshot(snapshot_id)
            snapshot_status = body['status']
            if 'error' in snapshot_status:
                raise exceptions.\
                    SnapshotBuildErrorException(snapshot_id=snapshot_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Share Snapshot %s failed to reach %s status '
                           'within the required time (%s s).' %
                           (snapshot_name, status, self.build_timeout))
                raise exceptions.TimeoutException(message)

    def wait_for_access_rule_status(self, share_id, rule_id, status):
        """Waits for a Share to reach a given status."""
        rule_status = "new"
        start = int(time.time())
        while rule_status != status:
            time.sleep(self.build_interval)
            resp, rules = self.list_access_rules(share_id)
            for rule in rules:
                if rule["id"] in rule_id:
                    rule_status = rule['state']
                    break
            if 'error' in rule_status:
                raise share_exceptions.\
                    AccessRuleBuildErrorException(rule_id=rule_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Share Access Rule %s failed to reach %s status '
                           'within the required time (%s s).' %
                           (rule_id, status, self.build_timeout))
                raise exceptions.TimeoutException(message)

    def default_quotas(self, tenant_id):
        resp, body = self.get("os-quota-sets/%s/defaults" % tenant_id)
        return resp, self._parse_resp(body)

    def show_quotas(self, tenant_id, user_id=None):
        uri = "os-quota-sets/%s" % tenant_id
        if user_id is not None:
            uri += "?user_id=%s" % user_id
        resp, body = self.get(uri)
        return resp, self._parse_resp(body)

    def reset_quotas(self, tenant_id, user_id=None):
        uri = "os-quota-sets/%s" % tenant_id
        if user_id is not None:
            uri += "?user_id=%s" % user_id
        return self.delete(uri)

    def update_quotas(self, tenant_id, user_id=None,
                      shares=None, snapshots=None,
                      gigabytes=None, force=True):
        put_body = {"quota_set": {}}
        put_body["quota_set"]["tenant_id"] = tenant_id
        if force:
            put_body["quota_set"]["force"] = "true"
        if shares is not None:
            put_body["quota_set"]["shares"] = shares
        if snapshots is not None:
            put_body["quota_set"]["snapshots"] = snapshots
        if gigabytes is not None:
            put_body["quota_set"]["gigabytes"] = gigabytes
        put_body = json.dumps(put_body)
        uri = "os-quota-sets/%s" % tenant_id
        if user_id is not None:
            uri += "?user_id=%s" % user_id
        resp, body = self.put(uri, put_body)
        return resp, self._parse_resp(body)

    def get_limits(self):
        resp, body = self.get("limits")
        return resp, self._parse_resp(body)

    def is_resource_deleted(self, *args, **kwargs):
        """Verifies deleted resource or not.

        :param kwargs: expected keys are 'share_id', 'rule_id',
        :param kwargs: 'snapshot_id', 'sn_id', 'ss_id'
        :raises share_exceptions.InvalidResource
        """

        if "share_id" in kwargs:
            share_id = kwargs.get("share_id")
            if "rule_id" in kwargs:
                __, rules = self.list_share_access_rules(share_id)
                for rule in rules:
                    if rule["id"] in kwargs.get("rule_id"):
                        return False
                return True
            else:
                try:
                    self.get_share(share_id)
                except exceptions.NotFound:
                    return True
        elif "snapshot_id" in kwargs:
            try:
                self.get_snapshot(kwargs.get("snapshot_id"))
            except exceptions.NotFound:
                return True
        elif "sn_id" in kwargs:
            sn_id = kwargs.get("sn_id")
            if "ss_id" in kwargs:
                __, ss_list = self.list_sec_services_for_share_network(sn_id)
                for ss in ss_list:
                    if ss["id"] in kwargs.get("ss_id"):
                        return False
                return True
            else:
                try:
                    self.get_share_network(sn_id)
                except exceptions.NotFound:
                    return True
        elif "ss_id" in kwargs:
            try:
                self.get_security_service(kwargs.get("sn_id"))
            except exceptions.NotFound:
                return True
        else:
            raise share_exceptions.InvalidResource(message=str(kwargs))
        return False

    def wait_for_resource_deletion(self, *args, **kwargs):
        """Waits for a resource to be deleted."""
        start_time = int(time.time())
        while True:
            if self.is_resource_deleted(*args, **kwargs):
                return
            if int(time.time()) - start_time >= self.build_timeout:
                raise exceptions.TimeoutException
            time.sleep(self.build_interval)

    def list_extensions(self):
        resp, extensions = self.get("extensions")
        return resp, self._parse_resp(extensions)

    def rename(self, share_id, name, desc=None):
        body = {"share": {"display_name": name}}
        if desc is not None:
            body["share"].update({"display_description": desc})
        body = json.dumps(body)
        resp, body = self.put("shares/%s" % share_id, body)
        return resp, self._parse_resp(body)

    def rename_snapshot(self, snapshot_id, name, desc=None):
        body = {"snapshot": {"display_name": name}}
        if desc is not None:
            body["snapshot"].update({"display_description": desc})
        body = json.dumps(body)
        resp, body = self.put("snapshots/%s" % snapshot_id, body)
        return resp, self._parse_resp(body)

    def reset_state(self, s_id, status="error", s_type="shares"):
        """
        Resets the state of a share or a snapshot
        status: available, error, creating, deleting, error_deleting
        s_type: shares, snapshots
        """
        body = {"os-reset_status": {"status": status}}
        body = json.dumps(body)
        return self.post("%s/%s/action" % (s_type, s_id), body)

###############

    def _update_metadata(self, share_id, metadata={}, method="post"):
        uri = "shares/%s/metadata" % share_id
        post_body = {"metadata": metadata}
        body = json.dumps(post_body)
        if method is "post":
            resp, metadata = self.post(uri, body)
        if method is "put":
            resp, metadata = self.put(uri, body)
        return resp, self._parse_resp(metadata)

    def set_metadata(self, share_id, metadata={}):
        return self._update_metadata(share_id, metadata)

    def update_all_metadata(self, share_id, metadata={}):
        return self._update_metadata(share_id, metadata, method="put")

    def delete_metadata(self, share_id, key):
        return self.delete("shares/%s/metadata/%s" % (share_id, key))

    def get_metadata(self, share_id):
        resp, body = self.get("shares/%s/metadata" % share_id)
        return resp, self._parse_resp(body)

###############

    def create_security_service(self, ss_type="ldap", **kwargs):
        # ss_type: ldap, kerberos, active_directory
        # kwargs: name, description, dns_ip, server, domain, sid, password
        post_body = {"type": ss_type}
        post_body.update(kwargs)
        body = json.dumps({"security_service": post_body})
        resp, body = self.post("security-services", body)
        return resp, self._parse_resp(body)

    def update_security_service(self, ss_id, **kwargs):
        # ss_id - id of security-service entity
        # kwargs: dns_ip, server, domain, sid, password, name, description
        # for 'active' status can be changed
        # only 'name' and 'description' fields
        body = json.dumps({"security_service": kwargs})
        resp, body = self.put("security-services/%s" % ss_id, body)
        return resp, self._parse_resp(body)

    def get_security_service(self, ss_id):
        resp, body = self.get("security-services/%s" % ss_id)
        return resp, self._parse_resp(body)

    def list_security_services(self):
        resp, body = self.get("security-services")
        return resp, self._parse_resp(body)

    def list_security_services_with_detail(self, params=None):
        """List the details of all shares."""
        uri = "security-services/detail"
        if params:
            uri += "?%s" % urllib.urlencode(params)
        resp, body = self.get(uri)
        return resp, self._parse_resp(body)

    def delete_security_service(self, ss_id):
        return self.delete("security-services/%s" % ss_id)

###############

    def create_share_network(self, **kwargs):
        # kwargs: name, description
        #+ for neutron: neutron_net_id, neutron_subnet_id
        body = json.dumps({"share_network": kwargs})
        resp, body = self.post("share-networks", body)
        return resp, self._parse_resp(body)

    def update_share_network(self, sn_id, **kwargs):
        # kwargs: name, description
        #+ for neutron: neutron_net_id, neutron_subnet_id
        body = json.dumps({"share_network": kwargs})
        resp, body = self.put("share-networks/%s" % sn_id, body)
        return resp, self._parse_resp(body)

    def get_share_network(self, sn_id):
        resp, body = self.get("share-networks/%s" % sn_id)
        return resp, self._parse_resp(body)

    def list_share_networks(self):
        resp, body = self.get("share-networks")
        return resp, self._parse_resp(body)

    def list_share_networks_with_detail(self, params=None):
        """List the details of all shares."""
        uri = "share-networks/detail"
        if params:
            uri += "?%s" % urllib.urlencode(params)
        resp, body = self.get(uri)
        return resp, self._parse_resp(body)

    def delete_share_network(self, sn_id):
        return self.delete("share-networks/%s" % sn_id)

    def action_with_share_network(self, sn_id, action="activate"):
        """Activates or deactivates share networks.

        param: sn_id: id of share-network
        param: action: available values are "activate" and "deactivate"
        returns: tuple with resp and body of response
        """

        body = json.dumps({action: {}})
        uri = "share-networks/%s/action" % sn_id
        resp, body = self.post(uri, body=body)
        return resp, self._parse_resp(body)

    def activate_share_network(self, sn_id):
        return self.action_with_share_network(sn_id, "activate")

    def deactivate_share_network(self, sn_id):
        return self.action_with_share_network(sn_id, "deactivate")

    def wait_for_share_network_status(self, sn_id, status="active"):
        """Waits for a Share network to reach a given status."""
        __, body = self.get_share_network(sn_id)
        sn_name = body['name']
        sn_status = body['status'].lower()
        start = int(time.time())

        while sn_status != status:
            time.sleep(self.build_interval)
            __, body = self.get_share_network(sn_id)
            sn_status = body['status'].lower()
            if 'error' in sn_status:
                # Error can be set only on attempt to activate
                raise share_exceptions.\
                    ShareNetworkActivationFailed(sn_id=sn_id)

            if int(time.time()) - start >= self.build_timeout:
                message = ('Share-network %s failed to reach %s status within '
                           'the required time (%s s).' %
                           (sn_name, status, self.build_timeout))
                raise exceptions.TimeoutException(message)

###############

    def _map_security_service_and_share_network(self, sn_id, ss_id,
                                                action="add"):
        # sn_id: id of share_network_entity
        # ss_id: id of security service entity
        # action: add, remove
        data = {
            "%s_security_service" % action: {
                "security_service_id": ss_id
            }
        }
        body = json.dumps(data)
        resp, body = self.post("share-networks/%s/action" % sn_id, body)
        return resp, self._parse_resp(body)

    def add_sec_service_to_share_network(self, sn_id, ss_id):
        return self._map_security_service_and_share_network(sn_id, ss_id)

    def remove_sec_service_from_share_network(self, sn_id, ss_id):
        return self._map_security_service_and_share_network(sn_id, ss_id,
                                                            "remove")

    def list_sec_services_for_share_network(self, sn_id):
        resp, body = self.get("security-services?share_network_id=%s" % sn_id)
        return resp, self._parse_resp(body)
