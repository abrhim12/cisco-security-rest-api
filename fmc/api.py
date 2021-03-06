import base64
from datetime import datetime
from time import sleep
import logging
from rest import AppClient, RestJSONHandler, RestClient
from collections import OrderedDict

logger = logging.getLogger(__name__)


class FMCError(Exception):
    pass


class FMCClient(AppClient):
    """
    AppClient extension for FMC.
    """
    def __init__(self, *args, **kwargs):
        self.AUTH_HTTP_STATUS = 204
        self.AUTH_REQ_HDR_FIELD = 'X-auth-access-token'
        self.AUTH_HDR_FIELD = 'X-auth-access-token'
        self.API_VERSION = 'v1'
        self.AUTH_URL = '/api/fmc_platform/' + self.API_VERSION + '/auth/generatetoken'
        # FMC REST API does not allow more than 120 requests per min
        self.req_time = datetime.now()
        self.req_count = 0
        super(FMCClient, self).__init__(*args, **kwargs)

    def login(self, *args, **kwargs):
        # Set basic HTTP authentication header
        base64str = base64.b64encode('{}:{}'.format(self.username, self.password))
        self.hdrs_auth["Authorization"] = "Basic {}".format(base64str)
        # Set HTTP method for login
        self.login_method = 'POST'
        # Call super!
        super(FMCClient, self).login(*args, **kwargs)

    def logout(self, *args, **kwargs):
        # Set API URL for logout
        self.LOGOUT_URL = '/api/fmc_platform/' + self.API_VERSION + '/auth/revokeaccess'

    def _req(self, *args, **kwargs):
        # ERR CODE 429: FMC REST API does not allow more than 120 requests per min
        self.req_count += 1
        if self.req_count == 1:
            self.req_time = datetime.now()
        elif self.req_count < 120:
            pass
        else:
            time_diff = (datetime.now() - self.req_time).total_seconds()
            if time_diff <= 60:
                sleep_time = 60 - time_diff + 1
                logger.info('FMC ratelimit < 120 req/min, sleeping for {} seconds'.format(sleep_time))
                sleep(sleep_time)
            self.req_count = 1
            self.req_time = datetime.now()
        method = kwargs['method']
        if method not in ['GET', 'POST', 'PUT', 'DELETE']:
            raise FMCError("HTTP method {} is not supported".format(method))

        super(FMCClient, self)._req(*args, **kwargs)


class FMCRestClient(RestClient, FMCClient, RestJSONHandler):
    """
    RestClient extension for FMC with FMCClient adn RestJSONHandler.

    Method Resolution Order:
    ```
    FMCRestClient
    RestClient
    FMCClient
    AppClient
    RestJSONHandler
    RestDataHandler
    object
    ```
    """
    pass


class FMC(FMCRestClient):
    """
    This class must be used to interact with FMC. Other classes are available within same module to interact with FMC
    resources such as Policy Objects, Devices, Access Policies.

    # Parameters
    url: URL of the FMC server
    username: Login username for FMC server. Ensure that appropriate user role and permissions are assigned
    to perform all the intended tasks.
    password: Login password for FMC server.

    """
    __v1_domain__ = '/api/fmc_config/v1/domain/default/'
    RESOURCE_TYPES = [
        'object', 'devices', 'devicegroups', 'policy',
        'assignment', 'job', 'audit', 'deployment']
    API_PATH = {  # Dictionary comprehension
        _res: '/api/fmc_config/v1/domain/default/' + _res + '/'
        for _res in RESOURCE_TYPES }
    # Looks like 'audit' is NOT a resource type
    # fmc_platform/v1/auth/generatetoken
    # fmc_platform/v1/auth/revokeaccess
    # fmc_platform/v1/domain/default/audit/
    API_PATH['audit'] = '/api/fmc_platform/v1/domain/default/audit/'
    POLICY_TYPES = [
        "accesspolicies", "filepolicies", "intrusionpolicies",
        "snmpalerts", "syslogalerts"]
    URL_OBJECT_TYPES = ['urls', 'urlgroups']
    NETWORK_OBJECT_TYPES = ['hosts', 'networks', 'ranges', 'networkgroups']
    PORT_OBJECT_TYPES = [
        "icmpv4objects", "icmpv6objects",
        'protocolportobjects', 'portobjectgroups']
    VLAN_OBJECT_TYPES = ['vlantags', 'vlangrouptags']
    REALM_USER_OBJECT_TYPES = ['realmusers', 'realmusergroups']
    CHILD_OBJECT_TYPES = {
        'networkgroups': NETWORK_OBJECT_TYPES,
        'portobjectgroups': PORT_OBJECT_TYPES,
        'urlgroups': URL_OBJECT_TYPES,
        'vlangrouptags': VLAN_OBJECT_TYPES,
        'realmusergroups': REALM_USER_OBJECT_TYPES
        }
    GROUP_OBJECT_TYPES = CHILD_OBJECT_TYPES.keys()
    OBJECT_TYPES = [
        "anyprotocolportobjects", "applicationcategories", "realms", "continents",
        "applicationfilters", "applicationproductivities", "ports", "tunneltags",
        "applicationrisks", "applications", "applicationtags", "applicationtypes",
        "countries", "variablesets", "endpointdevicetypes", "geolocations",
        "isesecuritygrouptags", "networkaddresses", "securitygrouptags",
        "siurlfeeds", "siurllists", "securityzones", "urlcategories"]
    OBJECT_TYPES += URL_OBJECT_TYPES + VLAN_OBJECT_TYPES + PORT_OBJECT_TYPES
    OBJECT_TYPES += NETWORK_OBJECT_TYPES + REALM_USER_OBJECT_TYPES
    RESOURCE_TREE = {
        'object': OBJECT_TYPES,
        'policy': POLICY_TYPES,
        'devices': ['devicerecords'],
        'devicegroups': ['devicegrouprecords'],
        'assignment': ['policyassignments'],
        'audit': ['auditrecords'],
        'job': ['taskstatuses'],
        'deployment': ['deployabledevices', 'deploymentrequests']
        }

    def __init__(self, url=None, username=None, password=None):
        """
        Initialize `FMC` object with server `URL`, `username` and `password` parameters.
        """
        super(FMC, self).__init__(url=url, username=username, password=password)
        self.server_version = ''
        self.get_server_version()
        self.obj_tables = OrderedDict()
        for obj_type in self.OBJECT_TYPES:
            self.obj_tables[obj_type] = FPObjectTable(self, type=obj_type)

    def _req_json(self, resource, type, oid=None, url=None, data=None):
        """
        Simple wrapper for _req with more options to make it resource agnostic and reusable in different classes
        """
        if oid:                         # Fetch the resource using instance ID
            url = self.url + self.API_PATH[resource] + type + '/' + oid

        resp = ''
        if url:                         # Fetch the resource using the URL
            resp = self._req(url)
        elif data:                      # Create resource using the data
            url = self.url + self.API_PATH[resource] + type
            logging.warning("Creating new {} {}: {}!".format(type, resource, data['name']))
            resp = self._req(url, method='POST', data=data)
        return resp

    def get_server_version(self):
        """
        GET FMC server version.
        """
        url = self.url + '/api/fmc_platform/v1/info/serverversion'
        resp = self._req(url)
        if len(resp):
            self.server_version = resp['items'][0]['serverVersion']
            logger.info('FMC {} Version is {}'.format(self.url, self.server_version))

    # Manage Devices
    def get_device_list(self):
        """
        Get the list of devices managed by FMC.
        :return:
        """
        url = self.url + self.API_PATH['devices'] + 'devicerecords'
        resp = self._req(url)
        return resp

    # Access Control Policies
    def create_access_policy(self, policy_data):
        url = self.url + self.API_PATH['devices'] + 'accesspolicies'
        resp = self._req(url, method='POST', data=policy_data)
        return resp

    def get_access_policy(self, oid):
        url = self.url + self.API_PATH['devices'] + 'accesspolicies/' + oid
        resp = self._req(url)
        return resp

    def get_all_policies(self, type):
        # Yield a policy at a time
        return self.get_all_resource_instances('policy', type)

    def get_all_resource_instances(self, resource, type):
        """
        Abstract generator function for iterating over instances of FMC resource types.
        """
        if resource not in self.RESOURCE_TYPES:
            raise FMCError("{} is not a valid resource!".format(resource))
        # Yield an object at a time
        if type not in self.RESOURCE_TREE[resource]:
            raise FMCError("{} type {} is not valid!".format(resource, type))

        # Fetch the first page
        # By default, URL = url + '?offset=0&limit=25&expanded=false'
        url = self.url + self.API_PATH[resource] + type + '?expanded=true'
        while url:  # True at least first page
            resp = self._req(url)
            if (not len(resp)) or (resp['paging']['count'] == 0):  # Return if No resource found.
                return
            for obj_item in resp['items']:
                # obj = self._req(obj_item['links']['self'])
                yield obj_item
            # Move to next page
            if 'next' in resp['paging'].keys():
                url = resp['paging']['next'][0]
            else:
                url = None
# End of FMC class


# Generic Resource Table related class and methods
class FPResourceTable(object):
    """
    Abstract class for table of instances of FMC resource types. It can be extended to make it specialized for
    specific resources, such as 'object', 'policy, 'devices, etc.

    `OrderedDict` is used so that child first order can be maintained for policy objects that allow for nested
    inheritance.
    """
    def __init__(self, fmc, resource, type):
        if resource not in fmc.RESOURCE_TYPES:
            raise FMCError("Resource type {} is not valid!".format(type))
            return
        if type not in fmc.RESOURCE_TREE[resource]:
            raise FMCError("{} type {} is not valid!".format(resource, type))
            return

        self.fmc = fmc
        self.resource = resource
        self.type = type
        self.names = OrderedDict()  # Mapping of 'name':'id'

    def __iter__(self):
        return self.fmc.get_all_resource_instances(self.resource, self.type)

    def build(self):
        """
        Build the 'names' dictionary for this table.
        names = {
            'resource1_name': 'resource1_id',
            'resource2_name': 'resource2_id'
            }
        """
        # Fetch the first page. By default,
        # URL = url + '?offset=0&limit=25&expanded=false'
        logger.info("Building names dictionary for {} {}s".format(self.type, self.resource))
        _fmc = self.fmc
        url = _fmc.url + _fmc.API_PATH[self.resource] + self.type + '?expanded=true'
        while url:  # True at least first page
            resp = _fmc._req(url)
            if not len(resp):  # Return if no resource found
                return
            if resp['paging']['count'] == 0:  # Return if no resource found
                return

            for obj_json in resp['items']:
                self.names[obj_json['name']] = obj_json['id']

            # Move to next page
            if 'next' in resp['paging'].keys():
                url = resp['paging']['next'][0]
                # DEFECT: FMC 6.1 does not preserve 'expanded=true' in subsequent URLs
                if 'expanded=true' not in url:
                    url += '&expanded=true'
                # resp = _fmc._req(url)
            else:
                url = None
        logger.debug(self.names)
# End of FPResourceTable class


class FPObjectTable(FPResourceTable):
    """
    Extends `FPResourceTable` for Policy Object related functionality. `FPObjectTable` allows `FMC` class to stay in
    sync with policy objects available in FMC. This helps with input data validation before it is sent to FMC server.
    FMC has its own input data validation mechanisms but customers prefer to send only necessary REST API requests to
    FMC and encounter as few errors as possible.

    In case of policy objects that allow for nested inheritance, such as network objects, table is built in child first
    order. This is achieved by using `OrderedDict` in `FPResourceTable`. This is very useful in data migration and
    cleanup especially between multiple FMCs and while executing test cases.

    Example usage:

    ```python
    >>> host_objs = FPObjectTable(FMC_object, 'hosts')
    >>> hosts_objs.type
    hosts
    >>> hosts_objs.names
    {}
    >>> hosts_objs.build()
    >>> hosts_objs.names
    {'host1_name': 'host1_id', 'host2_name': 'host2_id', ...}
    ```
    """
    def __init__(self, fmc, type):
        """
        FPObjectTable holds information about FMC objects.

        :param fmc: :class: `FMC` object
        :param type: FMC object type
        
        """
        super(self.__class__, self).__init__(fmc, 'object', type)

    def __iter__(self):
        """
        Generator function for FPObjectTable. It yields FPObject for
        for each item inside it.

        ```python
        >>> for fp_object in fmc.FPObjectTable(FMC_object, 'hosts'):
                print("fp_object.type, fp_object.name, fp_object.id")

        hosts hosts1_name hosts1_id
        hosts hosts2_name hosts2_id
        ```
        """
        for obj_json in super(self.__class__, self).__iter__():
            fp_obj = FPObject(self.fmc, self.type, json=obj_json)
            yield fp_obj

    def build(self):
        """
        Build the 'names' dictionary for this table.
        names = {
            'object1_name': 'object1_id',
            'object2_name': 'object2_id'
            }
        """
        # Fetch the first page. By default,
        # URL = url + '?offset=0&limit=25&expanded=false'
        logger.info("Building Objects Table for {} {}s".format(self.type, self.resource))
        _fmc = self.fmc
        url = _fmc.url + _fmc.API_PATH[self.resource] + self.type + '?expanded=true'
        while url:  # True at least first page
            resp = _fmc._req(url)
            if not len(resp):  # Return if no resource found
                return
            if resp['paging']['count'] == 0:  # Return if no resource found
                return
            for obj_json in resp['items']:
                # Make sure children names are listed before parent
                self.add_child_first(obj_json)
            # Move to next page
            if 'next' in resp['paging'].keys():
                url = resp['paging']['next'][0]
                # DEFECT: FMC 6.1 does not preserve 'expanded=true' in subsequent URLs
                if 'expanded=true' not in url:
                    url += '&expanded=true'
                    # resp = _fmc._req(url)
            else:
                url = None
        logger.debug(self.names)

    def add_child_first(self, obj_json):
        if obj_json.get("objects") is not None:
            for ch_item in obj_json["objects"]:
                ch_type = ch_item['type'].lower() + 's'
                if self.type == ch_type:
                    logger.debug("Found nested child {}".format(ch_item['name']))
                    ch_json = self.fmc._req_json(self.resource, type=self.type, oid=ch_item["id"])
                    # recursion for multi-level nesting - child-first order
                    self.add_child_first(ch_json)
        if self.names.get(obj_json['name']) is None:
            self.names[obj_json['name']] = obj_json['id']
# End of FPObjectTable class


class FPResource(object):
    def __init__(
            self, fmc, resource, type, oid=None,
            url=None, data=None, json=None):
        """
        FMC Generic Resource Manager API

        # Parameters
        fmc: FMC server object :class:`FMC` object.
        resource: FMC Resource
        type: Object type supported by Cisco FMC 6.1.0.
        json: (optional) Full object definition in :class dict: format.
        oid: (optional) Object ID, GET the object if provided.
        url: (optional) URL for the object, GET the object if provided.
        data: (optional) Data that will be accepted by Cisco FMC
            to create object when POST method is used.
        """
        if not (oid or url or data or json):
            logger.fatal("Cannot get FPResource with empty parameters")
            return
        self.fmc = fmc
        self.resource = resource
        self.type = type

        resp = self.fmc._req_json(self.resource, type=self.type, oid=oid, url=url, data=data)

        if len(resp):
            # True only if GET/POST operation was successful
            # DEFECT: POST/PUT response does NOT have description in it!!
            self.json = resp
        else:
            if data.get('name') is not None:
                logging.error("Creating new {} object: {}! FAILED!!".format(self.type, data['name']))
            else:
                logging.error("FAILED to get {} object!!".format(self.type))
            return  # new object is not added to the dictionary
    # End of FPObject.__init__

    @property
    def url(self):
        return self.json['links']['self']

    @property
    def name(self):
        return self.json['name']

    @property
    def id(self):
        return self.json['id']

    def __str__(self):
        return str(self.json)

    def __repr__(self):
        return "{}(type={}, name={}, id={})".format(
            self.__class__.__name__, self.type, self.name, self.id)


class FPObject(FPResource):
    """
    FMC Object Manager API

    Extends generic `FPResource` for Policy Object related methods. This class allows for extensive and flexible ways to
    perform CRUD operations on the policy objects and object inheritance as well.

    # Parameters
    fmc: FMC server object `FMC` object.
    type: (optional) Object type supported by Cisco FMC 6.1.0.
    oid: (optional) Object ID, GET the object, if provided.
    name: (optional) Object Name, GET the object, if provided.
    url: (optional) URL for the object, GET the object if provided.
    json: (optional) Full object definition in `dict` format.
    data: (optional) Data that will be accpeted by Cisco FMC to create object when POST method is used.
    obj: (optional) Another `FPObject` to duplicate. This is useful when migrating objects between different FMC
    servers.
    """
    def __init__(
            self, fmc, type=None, oid=None, name=None,
            url=None, json=None, data=None, obj=None):
        if not (oid or url or data or obj or json or name):
            logger.fatal("Cannot get FPObject with empty parameters")
            return
        self.fmc = fmc
        self.resource = 'object'
        if type and json:
            # Populate the object when '?expanded=true' is used in URL
            self.type = type
            self.json = json
            # Update names dictionary
            obj_names = self.fmc.obj_tables[self.type].names
            obj_names[self.name] = self.id
            return
        self.json = None

        if data is not None:
            type = data.get('type').lower() + 's'  # If data is provided, type should not be required
            if data.get("name") in self.fmc.obj_tables[type].names.keys():
                logging.warning("{}: Object name {} already exists!".format(self.fmc.url, data.get("name")))
                # Fetch the existing object using known object ID
                oid = self.fmc.obj_tables[type].names[data.get("name")]

        if obj:
            # This option helps duplicating objects from one FMC to
            # another FMC
            self.type = obj.type
            if obj.name in self.fmc.obj_tables[self.type].names.keys():
                logging.warning(
                    "{}: Object name {} already exists!".format(self.fmc.url, obj.name))
                # Fetch the existing object using known object ID
                oid = self.fmc.obj_tables[self.type].names[obj.name]
            else:
                data = obj.json.copy()
                for obj_key in ['id', 'links', 'metadata']:
                    data.pop(obj_key)
                if 'objects' in data.keys():
                    # Update child object IDs
                    for child_obj in data['objects']:
                        # Host -> hosts, Range -> ranges, Url -> urls
                        child_type = child_obj['type'].lower() + 's'
                        # Assumption is that the dictionary of 'name':'id'
                        # mapping is already populated
                        child_names = self.fmc.obj_tables[child_type].names
                        child_obj['id'] = child_names[child_obj['name']]
        elif type is not None and (type in self.fmc.OBJECT_TYPES):
            # If 'obj' is provided, then ignore 'type' parameter
            self.type = type
        else:
            logging.fatal("Object type not defined!!")

        if name is not None:
            oid = self.fmc.obj_tables[self.type].names[name]
            logging.debug("Looking for name {} and found id {}".format(name, oid))

        resp = self.fmc._req_json(resource='object', type=self.type, oid=oid, url=url, data=data)

        if len(resp): 
            # True only if GET/POST operation was successful
            # DEFECT: POST/PUT response does NOT have description in it!!
            self.json = resp
            # Update names dictionary
            obj_names = self.fmc.obj_tables[self.type].names
            obj_names[self.name] = self.id
        else:
            if data.get('name') is not None:
                logging.error("Creating new {} object: {}! FAILED!!".format(self.type, data['name']))
            else:
                logging.error("FAILED to get {} object: {}!!".format(self.type, obj.name))
            return  # new object is not added to the dictionary
    # End of FPObject.__init__

    def __repr__(self):
        return "{}(type={}, name={}, id={})".format(
            self.__class__.__name__, self.type, self.name, self.id)

    def update(self, data):
        """
        Update this object with new definition.
        
        # Parameters
        data: JSON data in dict() format for the new definition

        :return: JSON data of the object
        """
        logging.warning(
            "Updating {} object {}!".format(self.type, self.name))
        resp = self.fmc._req(
            self.json['links']['self'], 
            method='PUT', data=data)
        if len(resp):  # True only if PUT operation was successful
            self.json = resp
        return self.json

    def delete(self):
        """
        Delete this object from FMC server.
        """
        logging.warning("Deleting {} object: {}!".format(self.type, self.name))
        resp = self.fmc._req(self.json['links']['self'], method='DELETE')
        if len(resp):  # True only if DELETE operation was successful
            # Update names dictionary
            obj_names = self.fmc.obj_tables[self.type].names
            obj_names.pop(self.name)
        return resp

    def rename(self, new_name):
        """
        Rename this object.
        
        # Parameters
        new_name: New object name
        """
        if not new_name:
            logging.error("Cannot rename to empty string!")
            return new_name
        old_name = self.name
        put_data = self.json.copy()
        for obj_key in ['links', 'metadata']:
            put_data.pop(obj_key)
        put_data['name'] = new_name
        logging.warning(
            "Renaming {} object {}: {}!".
            format(self.type, self.name, new_name))
        self.update(put_data)
        if self.json['name'] == new_name:
            # Update names dictionary
            obj_names = self.fmc.obj_tables[self.type].names
            obj_names.pop(old_name)
            obj_names[self.name] = self.id
        else:
            logging.error("Renaming {} object {}: {} FAILED!!".format(self.type, self.name, new_name))
        return

    def get_child_object(self, child_name):
        """
        Fetch the child object from FMC. Used by 'add_children' method.
        
        # Parameters
        child_name: Name of the child object

        :return: Child object in FPObject format
        """
        children_types = self.fmc.CHILD_OBJECT_TYPES[self.type]
        for child_type in children_types:
            if child_name in self.fmc.obj_tables[child_type].names.keys():
                return FPObject(
                    self.fmc, type=child_type,
                    oid=self.fmc.obj_tables[child_type].names[child_name])

    def _update_json(self):
        """
        Changes to children affects parents so parents contents need to
        be updated when making changes to it.
        """
        self.json = self.fmc._req(self.url)
        
    def add_children(self, *children_names):
        """
        Add any number of objects to this object as a parent.
        
        # Parameters
        children_names: Comma separated names of child objects
        """
        self._update_json()
        put_data = self.json.copy()
        for obj_key in ['links', 'metadata']:
            put_data.pop(obj_key)
        if 'objects' not in put_data.keys():
            put_data['objects'] = []
        for child_name in children_names:
            child_obj = self.get_child_object(child_name)
            if not child_obj:  # Could not find valid child object
                return
            put_data['objects'].append({
                    "id": child_obj.json["id"],
                    "name": child_obj.json["name"],
                    "overridable": child_obj.json["overridable"],
                    "type": child_obj.json["type"]})
            logging.warning(
                "Adding {} object {} as a child to parent {}!".
                format(child_obj.json["type"], child_name, self.name))
        self.update(put_data)

    def remove_child(self, child_name):
        """
        Remove an existing child from this object as a parent.
        
        # Parameters
        child_name: Name of the child to remove
        """
        self._update_json()
        put_data = self.json.copy()
        for obj_key in ['links', 'metadata']:
            put_data.pop(obj_key)
        obj_children = put_data.pop('objects')
        put_data['objects'] = []
        child_type = ''
        for obj_child in obj_children:
            if obj_child['name'] != child_name:
                put_data['objects'].append(obj_child)
            else:
                child_type = obj_child['type']
        if child_type:
            logging.warning("Removing {} child object {} from parent {}!".format(child_type, child_name, self.name))
            self.update(put_data)
        else:
            logging.error("Child {} not found inside parent {}!".format(child_name, self.name))

    @property
    def parent_type(self):
        """
        Returns group object type if this object can be grouped under
        other object.
        """
        for ptype in self.fmc.GROUP_OBJECT_TYPES:
            if self.type in self.fmc.CHILD_OBJECT_TYPES[ptype]:
                return ptype

    def add_to_parent(self, pname):
        """
        Add this object inside another object as a child.
        
        # Parameters
        pname: Name of the parent object
        """
        if not pname:
            logging.error("Cannot add to invalid parent {}".format(pname))
            return pname
        parent_type = self.parent_type
        if pname not in self.fmc.obj_tables[parent_type].names.keys():
            logging.error("Could not find parent {} in FMC".format(pname))
            return pname
        parent_obj = FPObject(
            self.fmc, 
            type=parent_type,
            oid=self.fmc.obj_tables[parent_type].names[pname])
        put_data = parent_obj.json.copy()
        for obj_key in ['links', 'metadata']:
            put_data.pop(obj_key)
        if 'objects' not in put_data.keys():
            put_data['objects'] = []
        put_data['objects'].append({
                "id": self.json["id"],
                "name": self.json["name"],
                "overridable": self.json["overridable"],
                "type": self.json["type"]})
        logging.warning(
            "Adding {} object {} as a child to parent {}!".
            format(self.type, self.json['name'], pname))
        parent_obj.update(put_data)
        return

    def remove_from_parent(self, pname):
        """
        Remove this object from another parent object
        
        # Parameters
        pname: Name of the parent object
        """
        if not pname:
            logging.error("Cannot add to invalid parent {}".format(pname))
            return pname
        parent_type = self.parent_type
        if pname not in self.fmc.obj_tables[parent_type].names.keys():
            logging.error("Could not find parent {} in FMC".format(pname))
            return
        parent_obj = FPObject(
            self.fmc, 
            type=parent_type,
            oid=self.fmc.obj_tables[parent_type].names[pname])
        put_data = parent_obj.json.copy()
        if 'objects' not in put_data.keys():
            logging.error("Parent {} has no children to remove".format(pname))
            return
        for obj_key in ['links', 'metadata']:
            put_data.pop(obj_key)
        obj_children = put_data.pop('objects')
        put_data['objects'] = []
        for obj_child in obj_children:
            if obj_child['name'] != self.json['name']:
                put_data['objects'].append(obj_child)
        logging.warning(
            "Removing {} child object {} from parent {}!".
            format(self.type, self.json['name'], pname))
        parent_obj.update(put_data)
        return
# End of FPObject class


# Generic Object related class and methods
class FPPolicyTable(FPResourceTable):
    """
    Work In Progress
    """
    def __init__(self, fmc, type):
        super(self.__class__, self).__init__(fmc, 'policy', type)


class FPAccessRulesTable(FPResourceTable):
    """
    Work In Progress
    """
    def __init__(self, fmc, uuid):
        self.access_policy_uuid = uuid
        resource_type = 'policy/' + self.access_policy_uuid + '/accessrules'
        super(self.__class__, self).__init__(fmc, resource_type, type)


class FPAccessPolicy(object):
    """
    Work In Progress
    """
    def __init__(self, fmc, data=None, json=None, uuid=None, url=None, obj=None):
        """
        FMC Access Policy object

        :param fmc:
        :param data:
        :param json:
        :param uuid:
        :param url:
        :param obj:
        """
        if not (uuid or url or data or obj or json):
            logger.fatal("Cannot get FPObject with empty parameters")
            return
        self.fmc = fmc
        if json:
            # Populate the object when '?expanded=true' is used in URL
            self.json = json
            # Update names dictionary
            # obj_names = self.fmc.obj_tables[self.type].names
            # obj_names[self.name] = self.id
            return
        self.json = None

        if obj:
            # This option helps duplicating objects from one FMC to
            # another FMC
            self.type = obj.type
            if obj.name in self.fmc.obj_tables[self.type].names.keys():
                logging.warning("{}: Object name {} already exists!".format(self.fmc.url, obj.name))
                # Fetch the existing object using known object ID
                oid = self.fmc.obj_tables[self.type].names[obj.name]
            else:
                data = obj.json.copy()
                for obj_key in ['id', 'links', 'metadata']:
                    data.pop(obj_key)
                if 'objects' in data.keys():
                    # Update child object IDs
                    for child_obj in data['objects']:
                        # Host -> hosts, Range -> ranges, Url -> urls
                        child_type = child_obj['type'].lower() + 's'
                        # Assumption is that the dictionary of 'name':'id'
                        # mapping is already populated
                        child_names = self.fmc.obj_tables[child_type].names
                        child_obj['id'] = child_names[child_obj['name']]
        else:
            logging.fatal("Object type not defined!!")

        resp = self.fmc._req_json(resource='policy', oid=oid, url=url, data=data)

        if len(resp):
            # True only if GET/POST operation was successful
            # DEFECT: POST/PUT response does NOT have description in it!!
            self.json = resp
            # Update names dictionary
            obj_names = self.fmc.obj_tables[self.type].names
            obj_names[self.name] = self.id
        else:
            if data.get('name') is not None:
                logging.error("Creating new {} object: {}! FAILED!!".format(self.type, data['name']))
            else:
                logging.error("FAILED to get {} object: {}!!".format(self.type, obj.name))
            return  # new object is not added to the dictionary

    # End of FPObject.__init__

    @property
    def url(self):
        return self.json['links']['self']

    @property
    def name(self):
        return self.json['name']

    @property
    def id(self):
        return self.json['id']

    def __str__(self):
        return str(self.json)

    def __repr__(self):
        return "{}(type={}, name={}, id={})".format(
            self.__class__.__name__, self.type, self.name, self.id)


class FPDeviceTable(FPResourceTable):
    """
    Work In Progress
    """
    def __init__(self, fmc, type):
        super(self.__class__, self).__init__(fmc, 'devices', type)


class FPDeviceGroupTable(FPResourceTable):
    """
    Work In Progress
    """
    def __init__(self, fmc, type):
        super(self.__class__, self).__init__(fmc, 'devicegrouprecords', type)


