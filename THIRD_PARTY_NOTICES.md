# Third-party code and licenses

UCanDrop is based on Omdrop and OWL. It is an independent project and is not
affiliated with Apple, Ubuntu, Canonical or the upstream maintainers.

Different components retain their original licenses. UCanDrop-authored
components outside the MIT client, and changes to GPL-3.0 components, are
licensed under GPL-3.0-or-later; the root `LICENSE` contains its version 3 text.
This does not relicense the separately licensed components below. The client
and its changes retain MIT, and the radio-independent tools retain
GPL-2.0-only. Original copyright notices remain in source files and license
texts.

| Component | Source | License / notice |
| --- | --- | --- |
| Client, receiver and desktop integration | [omdrop-plugin](https://github.com/t4t5/omdrop-plugin), derived from brentkearney/omdrop-plugin | MIT; `client/LICENSE`, `licenses/omdrop-plugin-MIT.txt` |
| Radio-independent sending, identity, BLE and mDNS tools | [omdrop-awdl](https://github.com/brentkearney/omdrop-awdl) | GPL-2.0-only; `licenses/omdrop-awdl-GPL-2.0.txt` |
| Radio helper and driver profiles | [omdrop-owl](https://github.com/t4t5/omdrop-owl) | GPL-3.0-or-later; `licenses/omdrop-owl-copyright` |
| OWL AWDL implementation | [seemoo-lab/owl](https://github.com/seemoo-lab/owl), through [jedbillyb/owl](https://github.com/jedbillyb/owl) | GPL-3.0-or-later; `vendor/owl/COPYING`, `licenses/owl-GPL-3.0.txt` |
| Radiotap parser | OWL's pinned radiotap sources | ISC; `vendor/owl/radiotap/COPYING`, `licenses/radiotap-ISC.txt` |
| GoogleTest sources used by OWL's test build | OWL's pinned GoogleTest sources | BSD; license files in `vendor/owl/googletest/` |

The vendored OWL base is commit
`832d70f815c3d4a06a02117bf0fc5e868daa1ff0`. The included source incorporates
AWDL address and transmit-rate options, action-frame padding, and dynamic HT
receive capability advertisement. All source required to build the included
OWL implementation is present; its build does not fetch a different branch.

The receive changes retain complete archive and byte-count checks, reduce the
validated optional-terminator wait, and deliver URLs to the notification
listener without writing shortcut files. These modules are source code, not
captured transfers or user configuration.

Apple root/intermediate certificates bundled by the client are public trust
anchors from the upstream project. No user's certificate, private key, Apple
account record or keyring payload is included.
