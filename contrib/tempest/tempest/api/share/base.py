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

import inspect
import time

from tempest import clients_share as clients
from tempest.common import isolated_creds
from tempest.common.utils import data_utils
from tempest import config_share as config
from tempest import exceptions
from tempest import test

CONF = config.CONF


class BaseSharesTest(test.BaseTestCase):
    """Base test case class for all Manila API tests."""

    _interface = "json"
    force_tenant_isolation = False
    protocols = ["nfs", "cifs"]

    # Will be cleaned up in tearDownClass
    class_resources = []

    # Will be cleaned up in tearDown method
    method_resources = []

    # Will be cleaned up in tearDownClass
    class_isolated_creds = []

    # Will be cleaned up in tearDown method
    method_isolated_creds = []

    @classmethod
    def get_client_with_isolated_creads(cls,
                                        name=None,
                                        type_of_creds="admin",
                                        cleanup_in_class=False):
        """Creates isolated creds.

        :param name: name, will be used for naming ic and related stuff
        :param type_of_creds: admin, alt or primary
        :param cleanup_in_class: defines place where to delete
        :returns: SharesClient -- shares client with isolated creds.
        :returns: To client added dict attr 'creds' with
        :returns: key elements 'tenant' and 'user'.
        """
        if name is None:
            # Get name of test method
            name = inspect.stack()[1][3]
            if len(name) > 32:
                name = name[0:32]

        # Choose type of isolated creds
        ic = isolated_creds.IsolatedCreds(name)
        if "admin" in type_of_creds:
            creds = ic.get_admin_creds()
        elif "alt" in type_of_creds:
            creds = ic.get_alt_creds()
        else:
            creds = ic.get_primary_creds()

        # create client with isolated creds
        username, tenant_name, password = creds
        os = clients.Manager(username=username,
                             password=password,
                             tenant_name=tenant_name,
                             interface=cls._interface)
        client = os.shares_client

        # Get tenant and user
        identity_client = cls._get_identity_admin_client()
        client.creds = {}
        client.creds["tenant"] = identity_client.get_tenant_by_name(
            client.auth_params["tenant"])
        client.creds["user"] = identity_client.get_user_by_username(
            client.creds["tenant"]["id"],
            client.auth_params["user"])

        # Set quotas before tests
        value = 1000
        client.update_quotas(client.creds["tenant"]["id"],
                             shares=value,
                             snapshots=value,
                             gigabytes=value)
        client.update_quotas(client.creds["tenant"]["id"],
                             client.creds["user"]["id"],
                             shares=value,
                             snapshots=value,
                             gigabytes=value)

        # Set place where will be deleted isolated creds
        ic_res = {
            "method": ic.clear_isolated_creds,
            "deleted": False,
        }
        if cleanup_in_class:
            cls.class_isolated_creds.insert(0, ic_res)
        else:
            cls.method_isolated_creds.insert(0, ic_res)

        # Provide share network
        if CONF.share.multitenancy_enabled:
            if not CONF.service_available.neutron:
                raise cls.skipException("Neutron support is required")
            nc = os.network_client
            share_network_id = cls.provide_share_network(client, nc)
            client.share_network_id = share_network_id
            resource = {
                "type": "share_network",
                "id": client.share_network_id,
                "client": client,
            }
            if cleanup_in_class:
                cls.class_resources.insert(0, resource)
            else:
                cls.method_resources.insert(0, resource)
        return client

    @classmethod
    def verify_nonempty(cls, *args):
        if not all(args):
            msg = "Missing API credentials in configuration."
            raise cls.skipException(msg)

    @classmethod
    def setUpClass(cls):
        if not (any(p in CONF.share.enable_protocols
                    for p in cls.protocols) and
                CONF.service_available.manila):
            skip_msg = "Manila is disabled"
            raise cls.skipException(skip_msg)
        super(BaseSharesTest, cls).setUpClass()
        if not hasattr(cls, "os"):
            cls.username = CONF.identity.username
            cls.password = CONF.identity.password
            cls.tenant_name = CONF.identity.tenant_name
            cls.verify_nonempty(cls.username, cls.password, cls.tenant_name)
            cls.os = clients.Manager(interface=cls._interface)
        if CONF.share.multitenancy_enabled:
            if not CONF.service_available.neutron:
                raise cls.skipException("Neutron support is required")
            sc = cls.os.shares_client
            nc = cls.os.network_client
            share_network_id = cls.provide_share_network(sc, nc)
            cls.os.shares_client.share_network_id = share_network_id
        cls.shares_client = cls.os.shares_client

    def tearDown(self):
        super(BaseSharesTest, self).tearDown()
        self.clear_resources()
        self.clear_isolated_creds()

    @classmethod
    def tearDownClass(cls):
        super(BaseSharesTest, cls).tearDownClass()
        cls.clear_resources(cls.class_resources)
        cls.clear_isolated_creds(cls.class_isolated_creds)

    @classmethod
    def provide_share_network(cls, shares_client, network_client):
        """This is retry-wrapper for method "_provide_share_network".

        There is unique constraint for share-networks, it contains
        'tenant_id', 'neutron_net_id' and 'neutron_subnet_id'.
        Running tests with tempest in several threads can cause
        race condition, when we can get "http 400 bad request".
        """

        share_network_id = None
        timeout = int(time.time()) + 10
        while (share_network_id is None and (int(time.time()) < timeout)):
            try:
                share_network_id = cls._provide_share_network(shares_client,
                                                              network_client)
                break
            except exceptions.BadRequest:
                # Appears when suitable network and subnet exist, but no
                # share-network yet. More than one attempt to create
                # share-network were sent and unique constraint faced.
                time.sleep(1)
            except exceptions.Unauthorized:
                time.sleep(1)
        else:
            # Last attempt
            share_network_id = cls._provide_share_network(shares_client,
                                                          network_client)
        return share_network_id

    @classmethod
    def _provide_share_network(cls, shares_client, network_client):
        """Used for finding/creating share network for multitenant driver.

        This method creates/gets entity share-network for one tenant. This
        share-network will be used for creation of service vm.

        :param shares_client: shares client, which requires share-network
        :param network_client: network client from same tenant as shares
        :returns: str -- share network id for shares_client tenant
        :returns: None -- if single-tenant driver used
        """

        sc = shares_client

        if not CONF.share.multitenancy_enabled:
            # Assumed usage of a single-tenant driver
            share_network_id = None
        elif sc.share_network_id:
            # Share-network already exists, use it
            share_network_id = sc.share_network_id
        else:
            net_id = subnet_id = share_network_id = None

            # Search for networks, created in previous runs
            service_net_name = "share-service"
            __, networks = network_client.list_networks()
            if "networks" in networks.keys():
                networks = networks["networks"]
            for network in networks:
                if service_net_name in network["name"]:
                    net_id = network["id"]
                    if len(network["subnets"]) > 0:
                        subnet_id = network["subnets"][0]
                        break

            # Create suitable network
            if (net_id is None or subnet_id is None):
                ic = isolated_creds.IsolatedCreds(service_net_name)
                identity_client = cls._get_identity_admin_client()
                tenant = identity_client.\
                    get_tenant_by_name(sc.auth_params["tenant"])
                net_data = ic._create_network_resources(tenant["id"])
                network, subnet, router = net_data
                net_id = network["id"]
                subnet_id = subnet["id"]

            # Try get suitable share-network
            __, share_networks = sc.list_share_networks_with_detail()
            for share_network in share_networks:
                if (net_id in share_network["neutron_net_id"] and
                    subnet_id in share_network["neutron_subnet_id"]):
                    share_network_id = share_network["id"]
                    break

            # Create suitable share-network
            if share_network_id is None:
                sn_name = "autogenerated_by_tempest"
                sn_desc = "This share-network was created by tempest"
                __, sn = sc.create_share_network(name=sn_name,
                                                 description=sn_desc,
                                                 neutron_net_id=net_id,
                                                 neutron_subnet_id=subnet_id)
                share_network_id = sn["id"]

        return share_network_id

    @classmethod
    def create_share_wait_for_active(cls, share_protocol=None, size=1,
                                     name=None, snapshot_id=None,
                                     description=None, metadata={},
                                     share_network_id=None, client=None,
                                     cleanup_in_class=True):
        if client is None:
            client = cls.shares_client
        if description is None:
            description = "Tempest's share"
        if (share_network_id or client.share_network_id):
            share_network_id = share_network_id or client.share_network_id
            __, body = client.get_share_network(share_network_id)
            if body["status"].lower() == "inactive":
                resp, __ = client.activate_share_network(share_network_id)
                assert (int(resp["status"]) in test.HTTP_SUCCESS)
            client.wait_for_share_network_status(share_network_id,
                                                 "active")
        r, s = client.create_share(share_protocol=share_protocol, size=size,
                                   name=name, snapshot_id=snapshot_id,
                                   description=description,
                                   metadata=metadata,
                                   share_network_id=share_network_id)
        resource = {
            "type": "share",
            "id": s["id"],
            "client": client,
        }
        if cleanup_in_class:
            cls.class_resources.insert(0, resource)
        else:
            cls.method_resources.insert(0, resource)
        client.wait_for_share_status(s["id"], "available")
        return r, s

    @classmethod
    def create_snapshot_wait_for_active(cls, share_id, name=None,
                                        description=None, force=False,
                                        client=None, cleanup_in_class=True):
        if client is None:
            client = cls.shares_client
        if description is None:
            description = "Tempest's snapshot"
        r, s = client.create_snapshot(share_id, name, description, force)
        resource = {
            "type": "snapshot",
            "id": s["id"],
            "client": client,
        }
        if cleanup_in_class:
            cls.class_resources.insert(0, resource)
        else:
            cls.method_resources.insert(0, resource)
        client.wait_for_snapshot_status(s["id"], "available")
        return r, s

    @classmethod
    def create_share_network(cls, client=None,
                             cleanup_in_class=False, **kwargs):
        if client is None:
            client = cls.shares_client
        resp, sn = client.create_share_network(**kwargs)
        resource = {
            "type": "share_network",
            "id": sn["id"],
            "client": client,
        }
        if cleanup_in_class:
            cls.class_resources.insert(0, resource)
        else:
            cls.method_resources.insert(0, resource)
        return resp, sn

    @classmethod
    def create_security_service(cls, ss_type="ldap", client=None,
                                cleanup_in_class=False, **kwargs):
        if client is None:
            client = cls.shares_client
        resp, ss = client.create_security_service(ss_type, **kwargs)
        resource = {
            "type": "security_service",
            "id": ss["id"],
            "client": client,
        }
        if cleanup_in_class:
            cls.class_resources.insert(0, resource)
        else:
            cls.method_resources.insert(0, resource)
        return resp, ss

    @classmethod
    def clear_isolated_creds(cls, creds=None):
        if creds is None:
            creds = cls.method_isolated_creds
        for ic in creds:
            if "deleted" not in ic.keys():
                ic["deleted"] = False
            if not ic["deleted"]:
                ic["method"]()
                ic["deleted"] = True

    @classmethod
    def clear_resources(cls, resources=None):
        """Deletes resources, that were created in test suites.

        This method tries to remove resources from resource list,
        if it is not found, assumed it was deleted in test itself.
        It is expected, that all resources were added as LIFO
        due to restriction of deletion resources, that is in the chain.

        :param resources: dict with keys 'type','id','client' and 'deleted'
        """

        if resources is None:
            resources = cls.method_resources
        for res in resources:
            if "deleted" not in res.keys():
                res["deleted"] = False
            if "client" not in res.keys():
                res["client"] = cls.shares_client
            if not(res["deleted"]):
                res_id = res['id']
                client = res["client"]
                try:
                    if res["type"] is "share":
                        client.delete_share(res_id)
                        client.wait_for_resource_deletion(share_id=res_id)
                    elif res["type"] is "snapshot":
                        client.delete_snapshot(res_id)
                        client.wait_for_resource_deletion(snapshot_id=res_id)
                    elif res["type"] is "share_network":
                        __, body = client.get_share_network(res_id)
                        if body["status"].lower() == "active":
                            client.deactivate_share_network(res_id)
                            client.wait_for_share_network_status(res_id,
                                                                 "inactive")
                        client.delete_share_network(res_id)
                        client.wait_for_resource_deletion(sn_id=res_id)
                    elif res["type"] is "security_service":
                        client.delete_security_service(res_id)
                        client.wait_for_resource_deletion(ss_id=res_id)
                except exceptions.NotFound:
                    pass
                except exceptions.Unauthorized:
                    pass
                res["deleted"] = True

    @classmethod
    def generate_share_network_data(self):
        data = {
            "name": data_utils.rand_name("sn-name"),
            "description": data_utils.rand_name("sn-desc"),
            "neutron_net_id": data_utils.rand_name("net-id"),
            "neutron_subnet_id": data_utils.rand_name("subnet-id"),
        }
        return data

    @classmethod
    def generate_security_service_data(self):
        data = {
            "name": data_utils.rand_name("ss-name"),
            "description": data_utils.rand_name("ss-desc"),
            "dns_ip": data_utils.rand_name("ss-dns_ip"),
            "server": data_utils.rand_name("ss-server"),
            "domain": data_utils.rand_name("ss-domain"),
            "sid": data_utils.rand_name("ss-sid"),
            "password": data_utils.rand_name("ss-password"),
        }
        return data


class BaseSharesAltTest(BaseSharesTest):
    """Base test case class for all Shares Alt API tests."""

    @classmethod
    def setUpClass(cls):
        cls.username = CONF.identity.alt_username
        cls.password = CONF.identity.alt_password
        cls.tenant_name = CONF.identity.alt_tenant_name
        cls.verify_nonempty(cls.username, cls.password, cls.tenant_name)
        cls.os = clients.AltManager(interface=cls._interface)
        alt_share_network_id = CONF.share.alt_share_network_id
        cls.os.shares_client.share_network_id = alt_share_network_id
        super(BaseSharesAltTest, cls).setUpClass()


class BaseSharesAdminTest(BaseSharesTest):
    """Base test case class for all Shares Admin API tests."""

    @classmethod
    def setUpClass(cls):
        cls.username = CONF.identity.admin_username
        cls.password = CONF.identity.admin_password
        cls.tenant_name = CONF.identity.admin_tenant_name
        cls.verify_nonempty(cls.username, cls.password, cls.tenant_name)
        cls.os = clients.AdminManager(interface=cls._interface)
        admin_share_network_id = CONF.share.admin_share_network_id
        cls.os.shares_client.share_network_id = admin_share_network_id
        super(BaseSharesAdminTest, cls).setUpClass()
