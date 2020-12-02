import docker
import json
import sys
from jinja2 import Environment, PackageLoader


__version__ = "0.1.4"

try:
    client = docker.APIClient()
except docker.errors.DockerException:
    client = None


def get_nested(dct: dict, *keys: list):
    for key in keys:
        try:
            dct = dct[key]
        except KeyError:
            return None
    return dct


def get_network_by_id(network_id: str) -> dict:
    for item in client.networks():
        if item.get("Id") == network_id:
            return Network(item)


def get_service_by_id(service_id: str) -> dict:
    try:
        for item in client.services():
            if item.get("Id") == service_id:
                return Service(item)
    except docker.errors.APIError:
        return


class Network:
    def __init__(self, network):
        self._network = network

    @property
    def id(self):
        return self._network["Id"]

    @property
    def driver(self):
        return self._network["Driver"]

    @property
    def ifname(self):
        return (
            get_nested(self._network, "Options", "com.docker.network.bridge.name")
            or f"br-{self.id[:12]}"
        )

    @property
    def ingress(self):
        # used to mark public interfaces in docker swarm setups
        return self._network["Ingress"]

    @property
    def ip_masquerade(self):
        return (
            get_nested(
                self._network,
                "Options",
                "com.docker.network.bridge.enable_ip_masquerade",
            )
            or False
        )

    @property
    def prefix(self):
        ipam_config = get_nested(self._network, "IPAM", "Config")
        if not ipam_config:
            return False

        return ipam_config[0]["Subnet"]

    def inspect(self):
        return client.inspect_network(self.id)


class Service:
    def __init__(self, service):
        self._service = service

    @property
    def port_mappings(self):
        return [
            SwarmPortMapping(mapping, self)
            for mapping in get_nested(self._service, "Endpoint", "Ports")
        ]


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


class SwarmPortMapping(PortMapping):
    @property
    def proto(self):
        return self._mapping["Protocol"]

    @property
    def internal_port(self):
        return self._mapping["TargetPort"]

    @property
    def external_port(self):
        return self._mapping["PublishedPort"]

    @property
    def network(self):
        return self._container.networks[self._mapping["PublishMode"]]


class Container:
    def __init__(self, container):
        self._container = container

        self.networks = {
            name: get_network_by_id(network.get("NetworkID"))
            for name, network in get_nested(
                container, "NetworkSettings", "Networks"
            ).items()
        }
        self.service = get_service_by_id(
            get_nested(self._container, "Labels", "com.docker.swarm.service_id")
        )

        self.swarm = self.service is not None

    @property
    def id(self):
        return self._container["Id"]

    @property
    def ingress_networks(self):
        if self.swarm:
            return [network for network in self.networks.values() if network.ingress]

        return [
            network for network in self.networks.values() if network.driver == "bridge"
        ]

    @property
    def ip(self):
        addrs = []

        for network in self.ingress_networks:
            inspection = network.inspect()

            if self.id in inspection["Containers"]:
                addrs.append(
                    get_nested(inspection, "Containers", self.id, "IPv4Address").split(
                        "/"
                    )[0]
                )

        # TODO: this is too naïve, it should return the matching address for the network
        return addrs[0]

    @property
    def port_mappings(self):
        if self.swarm:
            return self.service.port_mappings

        return [
            PortMapping(mapping, self)
            for mapping in self._container.get("Ports", [])
            if "PublicPort" in mapping
        ]


def main():
    if not client:
        print("Docker API not reachable, doing nothing", file=sys.stderr)
        sys.exit(0)

    if len(sys.argv) > 1:
        if sys.argv[1] == "dump":
            dump()
            sys.exit(0)

    env = Environment(loader=PackageLoader("ferm_docker"))

    template = env.get_template("ferm.j2")

    # test for docker swarm
    try:
        client.services()
        swarm = True
    except docker.errors.APIError:
        # 503 Server Error: Service Unavailable ("This node is not a swarm manager. Use "docker swarm init" or "docker swarm join" to connect this node to swarm and try again.")
        swarm = False

    print(
        template.render(
            containers=list(map(Container, client.containers())),
            networks=list(map(Network, client.networks())),
            swarm=swarm,
        )
    )


def dump():
    for response in [client.containers(), client.networks()]:
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
