from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Comment:
    text: str


@dataclass
class BlankLine:
    pass


@dataclass
class Parameter:
    name: str
    value: str


@dataclass
class Option:
    name: str
    value: str


@dataclass
class Host:
    name: str
    body: list[Node] = field(default_factory=list)

    def get(self, name: str) -> str | None:
        for node in self.body:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                return node.value
        return None

    def set(self, name: str, value: str, as_option: bool = False) -> None:
        cls = Option if as_option else Parameter
        for node in self.body:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                node.value = value
                return
        self.body.append(cls(name, value))

    @property
    def mac(self) -> str | None:
        hardware = self.get("hardware")
        if hardware and hardware.startswith("ethernet "):
            return hardware.removeprefix("ethernet ").strip()
        return None

    def set_mac(self, mac: str) -> None:
        self.set("hardware", f"ethernet {mac}")

    @property
    def fixed_address(self) -> str | None:
        return self.get("fixed-address")

    def set_fixed_address(self, ip: str) -> None:
        self.set("fixed-address", ip)


@dataclass
class Subnet:
    network: str
    netmask: str
    body: list[Node] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.network}_{self.netmask}"

    @property
    def hosts(self) -> list[Host]:
        return [n for n in self.body if isinstance(n, Host)]

    def get(self, name: str) -> str | None:
        for node in self.body:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                return node.value
        return None

    def set(self, name: str, value: str, as_option: bool = False) -> None:
        cls = Option if as_option else Parameter
        for node in self.body:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                node.value = value
                return
        self.body.append(cls(name, value))


@dataclass
class Group:
    body: list[Node] = field(default_factory=list)

    @property
    def hosts(self) -> list[Host]:
        return [n for n in self.body if isinstance(n, Host)]


@dataclass
class UnknownBlock:
    header: str
    raw_body: str


Node = Comment | BlankLine | Parameter | Option | Host | Subnet | Group | UnknownBlock


@dataclass
class DhcpdConfig:
    nodes: list[Node] = field(default_factory=list)

    @property
    def subnets(self) -> list[Subnet]:
        return [n for n in self.nodes if isinstance(n, Subnet)]

    @property
    def top_level_hosts(self) -> list[Host]:
        hosts: list[Host] = []
        for n in self.nodes:
            if isinstance(n, Host):
                hosts.append(n)
            elif isinstance(n, Group):
                hosts.extend(n.hosts)
        return hosts

    @property
    def all_hosts(self) -> list[Host]:
        hosts = list(self.top_level_hosts)
        for subnet in self.subnets:
            hosts.extend(subnet.hosts)
        return hosts

    def find_subnet(self, key: str) -> Subnet | None:
        for subnet in self.subnets:
            if subnet.key == key:
                return subnet
        return None

    def find_host(self, name: str) -> Host | None:
        for host in self.all_hosts:
            if host.name == name:
                return host
        return None

    def get(self, name: str) -> str | None:
        for node in self.nodes:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                return node.value
        return None

    def set(self, name: str, value: str, as_option: bool = False) -> None:
        cls = Option if as_option else Parameter
        for node in self.nodes:
            if isinstance(node, (Parameter, Option)) and node.name == name:
                node.value = value
                return
        self.nodes.append(cls(name, value))

    def remove_subnet(self, key: str) -> bool:
        subnet = self.find_subnet(key)
        if subnet is None:
            return False
        self.nodes.remove(subnet)
        return True

    def remove_host(self, name: str) -> bool:
        for container in [self, *[n for n in self.nodes if isinstance(n, (Subnet, Group))]]:
            body = container.nodes if isinstance(container, DhcpdConfig) else container.body
            for node in body:
                if isinstance(node, Host) and node.name == name:
                    body.remove(node)
                    return True
        return False
