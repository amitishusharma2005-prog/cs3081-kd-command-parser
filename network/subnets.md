# Subnet allocation for 10.20.0.0/16

Method: sort requirements largest to smallest; for each, pick the smallest prefix with `2^(32-prefix) - 2 >= hosts`; place each block immediately after the previous one (start 10.20.0.0). Usable hosts = 2^(32-prefix) - 2 (network and broadcast addresses excluded).

## Working

- **app** needs 1000: /22 gives 2^10 - 2 = 1022 usable (/23 would give 2^9 - 2 = 510, too few). Block 10.20.0.0/22, next free address 10.20.4.0.
- **public** needs 250: /24 gives 2^8 - 2 = 254 usable (/25 would give 2^7 - 2 = 126, too few). Block 10.20.4.0/24, next free address 10.20.5.0.
- **data** needs 100: /25 gives 2^7 - 2 = 126 usable (/26 would give 2^6 - 2 = 62, too few). Block 10.20.5.0/25, next free address 10.20.5.128.
- **management** needs 20: /27 gives 2^5 - 2 = 30 usable (/28 would give 2^4 - 2 = 14, too few). Block 10.20.5.128/27, next free address 10.20.5.160.

## Table

| Subnet | Hosts needed | Network address | Prefix | Usable host range | Broadcast address | Usable hosts |
|---|---|---|---|---|---|---|
| app | 1000 | 10.20.0.0 | /22 | 10.20.0.1 - 10.20.3.254 | 10.20.3.255 | 1022 |
| public | 250 | 10.20.4.0 | /24 | 10.20.4.1 - 10.20.4.254 | 10.20.4.255 | 254 |
| data | 100 | 10.20.5.0 | /25 | 10.20.5.1 - 10.20.5.126 | 10.20.5.127 | 126 |
| management | 20 | 10.20.5.128 | /27 | 10.20.5.129 - 10.20.5.158 | 10.20.5.159 | 30 |

## Why replies need their own NACL rule, and why rule order matters (public subnet)

A network ACL is **stateless**: it does not remember that an outbound packet was the answer to an inbound request, so every packet is judged on its own against the rules for its direction. A client connects to port 443, but the load balancer answers to the client's *ephemeral* port (1024-65535). Allowing inbound 80/443 is therefore not enough: the outbound direction needs its own rule allowing TCP 1024-65535 to `0.0.0.0/0`, and the inbound direction needs one allowing the replies coming back from the app subnet (TCP 1024-65535 from `10.20.0.0/22`) after the load balancer calls the app on port 8000. Without those rules the replies hit the default deny and connections hang. (A stateful security group would allow them automatically.)

NACL rules are evaluated from the **lowest rule number upward and the first match wins**. The block on `198.51.100.0/24` must therefore have a lower number (100) than the allow rules for TCP 80/443 (110, 120). If the deny had a higher number, a packet from `198.51.100.9` to port 443 would match the allow rule first and the abusive range would get through.
