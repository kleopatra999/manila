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

from tempest.api.share import base
from tempest import test


class AdminActionsTest(base.BaseSharesAdminTest):

    @classmethod
    def setUpClass(cls):
        super(AdminActionsTest, cls).setUpClass()
        cls.states = ["error", "available"]
        __, cls.sh = cls.create_share_wait_for_active()
        __, cls.sn = cls.create_snapshot_wait_for_active(cls.sh["id"])

    @test.attr(type=["gate", ])
    def test_reset_share_state(self):
        for status in self.states:
            resp, __ = self.shares_client.reset_state(self.sh["id"],
                                                      status=status)
            self.assertIn(int(resp["status"]), test.HTTP_SUCCESS)
            self.shares_client.wait_for_share_status(self.sh["id"], status)

    @test.attr(type=["gate", ])
    def test_reset_snapshot_state_to_error(self):
        for status in self.states:
            resp, __ = self.shares_client.reset_state(self.sn["id"],
                                                      s_type="snapshots",
                                                      status=status)
            self.assertIn(int(resp["status"]), test.HTTP_SUCCESS)
            self.shares_client.wait_for_snapshot_status(self.sn["id"], status)
