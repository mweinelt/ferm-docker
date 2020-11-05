import docker
import json
from jinja2 import Environment, PackageLoader


__version__ = "0.1.1"

client = docker.APIClient()

def get_nested(dct, *keys):
    for key in keys:
        try:
            dct = dct[key]
        except KeyError:
            return None
    return dct


def get_network_by_id(network_id: str) -> dict:
    networks = client.networks()

    for network in networks:
        if network.get("Id") == network_id:
            return Network(network)


class Network:
    def __init__(self, network):
        self._network = network

    @property
    def _id(self):
        return self._network["Id"]

    @property
    def driver(self):
        return self._network["Driver"]

    @property
    def ifname(self):
        return get_nested(self._network, "Options", "com.docker.network.bridge.name") or f"br-{self._id[:12]}"

    @property
    def prefix(self):
        return get_nested(self._network, "IPAM", "Config").pop()["Subnet"]


class PortMapping:
    def __init__(self, mapping, container):
        self._mapping = mapping
        self._container = container

    @property
    def proto(self):
        return self._mapping["Type"]

    @property
    def internal_port(self):
        return self._mapping["PrivatePort"]

    @property
    def external_port(self):
        return self._mapping["PublicPort"]


class Container:
    def __init__(self, container):
        self._container = container

        self.network = get_network_by_id(self.network_id)

    @property
    def network_name(self):
        return get_nested(self._container, "HostConfig", "NetworkMode")

    @property
    def network_id(self):
        network_id = get_nested(self._container, "NetworkSettings", "Networks", self.network_name, "NetworkID")
        assert network_id is not None
        return network_id

    @property
    def ip(self):
        return get_nested(self._container, "NetworkSettings", "Networks", self.network_name, "IPAddress")

    @property
    def port_mappings(self):
        required_keys = ["Type", "PrivatePort", "PublicPort"]
        return [PortMapping(mapping, self) for mapping in self._container["Ports"] if all([key in mapping for key in required_keys])]



def main():
    env = Environment(
         loader=PackageLoader('ferm_docker')
    )

    template = env.get_template("ferm.j2")

    print(template.render(
        containers=list(map(Container, client.containers())),
        networks=list(map(Network, client.networks()))
    ))

if __name__ == '__main__':
    main()
