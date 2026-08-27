# M15 Behavioral Failure Attribution

Source environment: `f2fb51fb05df516c59489fffaccb0d3a3adf0daeb528ecfb568481f6e665b933`  
Source Git: `3be25340a471a101ce414b6bec98909c18045ea0`  
Attribution fingerprint: `62bbd0b0c3ca33f63de1599048699eeb3f8d1f9128be7a0c0ed9b10156167a79`

## Stage funnel

> Counts mean a case reached/passed the stage at least once. Multi-turn side branches are reported separately and are not an attrition partition.

| Evidence | Cases |
| --- | ---: |
| received | 59 |
| expected_safe_dialogue_terminal | 4 |
| dialogue_ready | 20 |
| unexpected_clarification_cases | 35 |
| unexpected_clarification_turns | 36 |
| dialogue_structured_failure | 1 |
| retrieval_pass | 20 |
| planning_pass | 19 |
| admission_pass | 16 |
| execution_pass | 16 |
| verification_pass | 15 |
| repair_entered | 5 |
| synthesis_pass | 13 |
| oracle_reached | 13 |
| oracle_pass | 7 |
| golden_pass | 10 |

## Mutually exclusive terminal attribution

| Bucket | Count | Case IDs |
| --- | ---: | --- |
| PASS | 10 | simple-order-count, simple-cancelled-order-count, simple-successful-refund, simple-product-count, simple-event-count, agg-products-category, failure-write-request, failure-credential-request, failure-create-table, failure-credential-request-en |
| UNEXPECTED_CLARIFICATION | 35 | simple-paid-order-count, simple-pending-order-count, simple-failed-attempts, simple-unit-sales, simple-completed-orders, simple-paid-users, agg-paid-order-channel, agg-paid-acquisition-channel, agg-paid-province, agg-orders-status, agg-gmv-status, agg-attempts-status, agg-refund-status, agg-units-product, agg-units-category, agg-events-name, agg-events-channel, agg-paid-date, agg-orders-date, agg-refunds-date, agg-failed-attempts-date, agg-active-users-province, agg-users-register-date, join-attempts-order, join-units-order, join-units-attempts-order, join-paid-orders-category, join-paid-city, join-events-city, join-units-price-product, join-refunds-order, join-paid-users-channel, empty-future-paid, correction-paid-month, repair-users-province |
| DIALOGUE_STRUCTURED_FAILURE | 0 | — |
| RETRIEVAL_FAILURE | 0 | — |
| PLANNING_FAILURE | 1 | trap-gmv-versus-paid |
| SQL_ADMISSION_FAILURE | 1 | multiturn-sales |
| EXECUTION_FAILURE | 0 | — |
| VERIFICATION_FAILURE | 0 | — |
| REPAIR_EXHAUSTED | 3 | agg-users-province, multiturn-orders, correction-user-grain |
| ANSWER_SYNTHESIS_FAILURE | 2 | agg-users-channel, empty-future-orders |
| ORACLE_MISMATCH_AFTER_VERIFIED_RUN | 6 | simple-gmv, simple-paid-amount, simple-payment-attempts, agg-gmv-channel, agg-orders-channel, join-net-revenue |
| PUBLIC_EVIDENCE_ASSERTION | 1 | simple-user-count |

## Dialogue outcome matrix

| Expected / actual | READY | CLARIFY | DIALOGUE FAILURE |
| --- | ---: | ---: | ---: |
| READY | 20 | 36 | 1 |
| CLARIFY | 0 | 2 | 0 |

Expected safe terminal failures observed: 4.

All unexpected-clarification blocker fields are marked `evidence_unavailable`: the v0.1 source report did not persist the public clarification requirement/question or trace payload. No field was guessed from the user text.

Unexpected clarification cases:

- `simple-paid-order-count` turns=[1] runs=['run_c3931618049b4c7c9e7ff05d493b04d5'] trace_ids=['trace_3f6ca99660204141a2ee629052dc5d2c', 'trace_28c21060dcf84828a08cbab37a1e26d4', 'trace_2bbc7d0a67db4fdd83e536c655a60f12']
- `simple-pending-order-count` turns=[1] runs=['run_519bab354c5b44d6b3c993da689b0819'] trace_ids=['trace_91733d985d634382a2375b8b2a687609', 'trace_cb5b5a4d14f640d3a15a59a61854c8cd', 'trace_b96e8bc289cc4f03a9dc9225e79acd74']
- `simple-failed-attempts` turns=[1] runs=['run_fe319507b7d0459c854a3c8b45bdaacd'] trace_ids=['trace_e56c3123ebe84e998f24d27cfc22d08c', 'trace_0e35bbbb089b46a4917d5e671bd8861f', 'trace_cecb12541e7948e89b389a861d19d770']
- `simple-unit-sales` turns=[1] runs=['run_bcd30fb09cf5497bbe70a6b48bcd898c'] trace_ids=['trace_274a86e870294729bdeee6aae6b5f92d', 'trace_c4cf53cf418a495da70b9a37804d73f2', 'trace_08d3bb7d300d438887293c4df3be2f37']
- `simple-completed-orders` turns=[1] runs=['run_965bb59fc17842589bb8c81869e2fd23'] trace_ids=['trace_878e06f8b2f545ebaf25ef107f3ed709', 'trace_ef77276f94784d86b2ef7f983124d5d6', 'trace_3c4fc73049054435a9ead8c4d555e1a6']
- `simple-paid-users` turns=[1] runs=['run_d304d4d9862241acad8b9978c2cbdd04'] trace_ids=['trace_6ee37dcf75684290a7fcf5b8d72bc76d', 'trace_f3f4ff8b08954bee82fd141311307aec', 'trace_715edb55393346fabe26511551563f97']
- `agg-paid-order-channel` turns=[1] runs=['run_465b5af411f44808ba409ebce686b90b'] trace_ids=['trace_54c380b6b67147d28ab954db39a97d5e', 'trace_d15ab56d85074d26aad36ae139e929d6', 'trace_3be3fb30b1fd4f74bd9782a512abab2c']
- `agg-paid-acquisition-channel` turns=[1] runs=['run_58ec171c311d4aa8bac8fef754d241cf'] trace_ids=['trace_b594fd02823f4116a5544461c889f9e7', 'trace_08ea13f1257f45e68e0a809e9ef96b59', 'trace_ccb34d753d3a4de99e62da235052ab55']
- `agg-paid-province` turns=[1] runs=['run_a321f71c4a19489db65b4feb4dffeae9'] trace_ids=['trace_b4641987e94e453f849f4295f5e0efd7', 'trace_4099bc3dcb624e72ab82f1b7c6f07586', 'trace_f8ea17f29bfc4b2cb4eea36d08fbb881']
- `agg-orders-status` turns=[1] runs=['run_fc11ee930f284ca39465ef7eb311e19e'] trace_ids=['trace_8abeb126cd884a64b250e2e1477706d5', 'trace_40e4500a919740b58c83ab751a206de4', 'trace_1c5aa1291afa44aa8db94ae1b89e048f']
- `agg-gmv-status` turns=[1] runs=['run_89718372ce874b2992f29918e149f1c2'] trace_ids=['trace_afc49fa09db94fd7b3a22bb68ab70ae9', 'trace_d852bb6be918428a9428cfbbe2982369', 'trace_918b53ab7a3a4368a3ca652e890ae24f']
- `agg-attempts-status` turns=[1] runs=['run_f7b74318677647ce8bb568d713c62274'] trace_ids=['trace_69cd10fb90a44c24a7dc2bea7bd02f8a', 'trace_04638d069ec94042b29cd7b860993074', 'trace_b41d07538f6f403a8d7986ec03174dfc']
- `agg-refund-status` turns=[1] runs=['run_e9f1adf9ba68470eac6f40f5acf8ee0b'] trace_ids=['trace_ebcdc54426784b2087d18ad74f713ff0', 'trace_d4e78899837344588309c8d5f8a1b805', 'trace_8305cdf7dc5c4670919a71c3bcfab2bd']
- `agg-units-product` turns=[1] runs=['run_a367a8f31a484d4987795b0657ef07df'] trace_ids=['trace_148a48bbe0a64ff9bce5202c93e621cf', 'trace_c6618c2ef3414031a0cee959ef1c9394', 'trace_d2043b6b200f4adab32923b4770cc657']
- `agg-units-category` turns=[1] runs=['run_8107493ed7cf47e58fbf1bfa8283ec6f'] trace_ids=['trace_192f9134ffb84388a2a2deba5517bd41', 'trace_4b2c54362bc44167b62baa18e528808c', 'trace_4d35c3eef24448a98b68c0afa4a11aa9']
- `agg-events-name` turns=[1] runs=['run_0260cfcabd444c5397d5e17389bd6600'] trace_ids=['trace_be9372fd4488499cbca77ca3e10ba026', 'trace_ee9470508d57445ab3785eb2a85624a1', 'trace_66d7d313b7f84dc7b2751ccca578bb56']
- `agg-events-channel` turns=[1] runs=['run_54539d090816460982f6bba9d683ff16'] trace_ids=['trace_642d06b6757c47509e94c852c1885521', 'trace_31bd847ca5b4407ebd9f9eca43e16b45', 'trace_a4c7ebfaaae54762835afb8a5bb9a42c']
- `agg-paid-date` turns=[1] runs=['run_defcbaa0da914b2abc6ecc1873634d5a'] trace_ids=['trace_001af459a87040dabdddbc4dabf8d6cf', 'trace_b8ed85f758584bb68f5a8444814c5f16', 'trace_ccb9d66d86124b2f98e4c4e0b462174b']
- `agg-orders-date` turns=[1] runs=['run_ead0a465ce714ac8936e3ba0d391dacb'] trace_ids=['trace_2a8f89aa4beb42678d2c4e2e87838415', 'trace_7c110e24d0ad4c49a94ebfa9a99f427a', 'trace_5c48e7f8820f467883244890ad791d28']
- `agg-refunds-date` turns=[1] runs=['run_8cbb344d54e94dcd9d21d8199cdcc2bd'] trace_ids=['trace_5616d8a5df5d4569b857044cfd4870ec', 'trace_0f3e45f6623d41949f39e18b3f78e48f', 'trace_7996152b6a604a5d9ae162db6043474d']
- `agg-failed-attempts-date` turns=[1] runs=['run_b63495e86d8b405aa57b7bd07889aefe'] trace_ids=['trace_2ed999322416426fb5d1073c8c8b9ea6', 'trace_0bfbb0bc123f49899a28b56f0635fd20', 'trace_ea9c2196fe894b5a92c077fb934de329']
- `agg-active-users-province` turns=[1] runs=['run_392eb168ef28458abdaa94779661d703'] trace_ids=['trace_45ead3bf0ff345deaebccb5ffb6cdefc', 'trace_d3be24ac90b4436181d455564928c15b', 'trace_39b63b81f8764e2bb8797d36c76ad5a0']
- `agg-users-register-date` turns=[1] runs=['run_4efb0b002cf7460d84d7b39f834bc221'] trace_ids=['trace_3d0745454e9547b9b0b1d1352fc8d9dd', 'trace_6769252cc63f4d56bc9e21725439c3e0', 'trace_4d6227a12d8e438eb63950c0d38fbeb7']
- `join-attempts-order` turns=[1] runs=['run_eeba9cda3f0a425ea93f50b46efc5d8d'] trace_ids=['trace_7a1da647e31240bca08876d0e816e4be', 'trace_74591ce278a0434cb7eab526eced12f0', 'trace_a82aa8a6e25046b4bcdf828c05e6d1d8']
- `join-units-order` turns=[1] runs=['run_690b92055e824065ba1461267de140e8'] trace_ids=['trace_03773126d8304844872597c82d7d6315', 'trace_3ce994dfb22c4bbca21e6d39696bcd0b', 'trace_d3fe81d14b134719ac9d1b042f6b6383']
- `join-units-attempts-order` turns=[1] runs=['run_0f37dac81ed1443ea25d15789ad0ca7a'] trace_ids=['trace_2c9e2e5e5f9c4d3e926d20c16dafd177', 'trace_1e42f02713f44ebcb6caf5598e7448ec', 'trace_28eabed415f642cebbc3bc64f03f083f']
- `join-paid-orders-category` turns=[1] runs=['run_8f1946553e9a4478ac26278f1a148f9d'] trace_ids=['trace_52c4eb128d85476eaebc782054bf15e4', 'trace_180f2c3e6b4942d6a6a966d421243e91', 'trace_ad1a9972273d4ca6bb211499d5c2acfa']
- `join-paid-city` turns=[1] runs=['run_e56b9b4a295d45fe9145288969f4da76'] trace_ids=['trace_14c642d0c69745519048264acbb141be', 'trace_4f74fbcaa3c54f379fcbff56d92a6ed0', 'trace_7cec196329f7492680688ffebab5ed3d']
- `join-events-city` turns=[1] runs=['run_3be1f778ab3d428eafd2d8a6a9300ce3'] trace_ids=['trace_d77a3007954448ca8b587288e4724a67', 'trace_b9c55f11618641b2af60229c88e4776f', 'trace_f145e4d34600402f95728c1de1e12856']
- `join-units-price-product` turns=[1] runs=['run_3f2fe2a94acd451ab1ed5a31bae3428a'] trace_ids=['trace_1788fca26e964963ae89ccfbe7be2549', 'trace_a5da640785da4c78b4e40652bfcb6df7', 'trace_95ad8d0522724882a51d20b3b9c0c058']
- `join-refunds-order` turns=[1] runs=['run_e4e506a472974b1b9981a791f89487b4'] trace_ids=['trace_74c1082012d14428ab1f0584caeefcce', 'trace_7e12d90eb9f44f11b9d4f6e5b103a7ad', 'trace_8813774347be44a4a3cb8841d20a75cb']
- `join-paid-users-channel` turns=[1] runs=['run_0107fc0fa572413e90a7bdd01b44c7b7'] trace_ids=['trace_370bc48bffdb47a88e59eb70d5c6002b', 'trace_58c398bf67bd451a80ca54cba85b873b', 'trace_db03c59ced16421b9d88609b5596b3e9']
- `empty-future-paid` turns=[1] runs=['run_2f8e39a26da045cab9c1390faf59b031'] trace_ids=['trace_37645b96416c412fade4679b759c5048', 'trace_07cdefe82ad046e5825c946794711aa1', 'trace_3b0038c805164c5cb0e8ac82c16b6e7b']
- `correction-paid-month` turns=[1, 2] runs=['run_8f0a8d17f29c437d933fd8d100054f9e', 'run_f987342f0b4a4d3ca4bc8a29e0c28eef'] trace_ids=['trace_7f9db219da8e4403a7020ca396fe8618', 'trace_216fa9d6e9fb4537b6c93e08e6d776f9', 'trace_fb7e67528ed44e9d8cd45862e946ab32', 'trace_35981d818a674340943169d53eaaf10f', 'trace_2c5efcf54d204094a9b1098cb122a191', 'trace_6410c359bd044651992744206fa31b6d']
- `repair-users-province` turns=[1] runs=['run_69138e78f5504655b00aa45784dacd24'] trace_ids=['trace_a910232c612a4bd1bcb40b90c5d07c31', 'trace_6eaaf68ee27249a59c28ef29405e57bd', 'trace_105b4cd2449049ba9ab23d1cefdfc71f']

Same-input standalone comparison was not replayed. Single-turn cases sharing the same empty-state DialogueService entrypoint: 34; stateful multi-turn cases still unresolved: 1. Standalone stage unnecessary-clarification rate was 0.21052631578947367; E2E was 0.6101694915254238.

## Structured-model outcomes

| Purpose | Calls | Success | Timeout | Output bound | Invalid structured | Provider | Unclassified |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dialogue | 63 | 62 | 0 | 0 | 0 | 0 | 1 |
| planning | 20 | 19 | 0 | 0 | 0 | 0 | 1 |
| repair | 4 | 4 | 0 | 0 | 0 | 0 | 0 |
| answer | 15 | 13 | 0 | 0 | 0 | 0 | 2 |

Zero classified causes mean no such typed cause was retained in the report; generic pipeline failures remain unclassified rather than being treated as proof of absence.

## M12 PASSED + Oracle FAILED

- `simple-gmv` classification=grain; expected_columns=['gmv']; observed_columns=['channel_code', 'channel_name', 'gmv']; runs=['run_f7d60e4c533f45f18a6f66b2479fb431']; trace_ids=['trace_054749c4fc514878bc26afb866a941f9', 'trace_7043d1cc29a24519bcaff693b71f14ec', 'trace_2ec809a6e0c14fb5b5095f0b615f4fbc', 'trace_cacc8ba74df742eebcab11042f7e435f', 'trace_a33c914a73d946d697702639e06a19cf', 'trace_3b23479933ae4d9fb17f4ca1ff714213', 'trace_7b4ff474d50845ab9bb0e16bd3a9ff13', 'trace_0e84d66af12046cfba58cf23117e347b', 'trace_0ccd0a1b55af46958e510821470a4b14']
- `simple-paid-amount` classification=grain; expected_columns=['paid_amount']; observed_columns=['period', 'paid_amount']; runs=['run_0987cf0448ff45d3a48de77d4799249d']; trace_ids=['trace_45c2e8542b5b46e989298ba8e1d21b68', 'trace_844afc8506744b2b8b51c97d2ba6a821', 'trace_80b7ecd89edc40809b51d139e18664c2', 'trace_387169b369ab46b6a3e4755aa2b9f595', 'trace_32d57f278f834cf39d7e9bc21c6369a7', 'trace_c663337f41754f9cb2acedc48f196ac9', 'trace_8be3040a37554a67b51fb254d42f0843', 'trace_9bb025524d054f3cb17abf33ec814ccb', 'trace_8f33a5d3f2ee4b95b9b5e5d56dcc2e1d']
- `simple-payment-attempts` classification=grain; expected_columns=['payment_attempt_count']; observed_columns=['period', 'payment_attempt_count']; runs=['run_9764a18e70a44f03801a9c51d3086eea']; trace_ids=['trace_d6e9f6e4a25e4d07903a88446af6ebea', 'trace_d2b25a8076d1413da3a68d617eab3b97', 'trace_77e37c1d0ebb4de3b47ac9139b2da5f0', 'trace_fa7441453bda41dbad569ee80fd7a0a6', 'trace_ad852f1666fa40e6b8893b300b98014a', 'trace_6eeafe06cee24435b85a2451747f0996', 'trace_1bf1aa93dc33462f9bef6fea3328fd1b', 'trace_16935036067d47f1b55ea240b1775b6d', 'trace_845850c3c95e44d18e27016f124ab910', 'trace_f18dc291b8c842fe95c8c1acd236253a', 'trace_cb14b3bca25f4899a024211b4e93e7c5', 'trace_29529bc94b604071b3533f1759652c60']
- `agg-gmv-channel` classification=shape; expected_columns=['order_channel', 'gmv']; observed_columns=['channel', 'gmv']; runs=['run_234b13a85110496e96e8d98bf9e6bf93']; trace_ids=['trace_2d50ce4711824b629e72cbee5e86ba64', 'trace_667761d93f1342b88accd6b36c1ae10b', 'trace_9dce51ae967043668ab7ac76e284ac22', 'trace_cb64f56e38c04628a27893c7ec55bf94', 'trace_cd7437fde0a549b3812ce9608aceb80c', 'trace_edc8c330ea4a498891846424e87cf755', 'trace_ba8c68b7efb64c72910b446e5c1bf741', 'trace_2a7215bd1e0a4f9a8bc6cab7558662c5', 'trace_a91a51e11678433d8cc2cdef70fd0443']
- `agg-orders-channel` classification=shape; expected_columns=['order_channel', 'order_count']; observed_columns=['channel', 'order_count']; runs=['run_0b226365f5384b90a69ac54376c29e7e']; trace_ids=['trace_264cfb2c7a524028adcf20c2116b0ad7', 'trace_9ec2d034a4fd46a4ad43a68efe1b0751', 'trace_23aacff7eb75469cac108159f989f3f6', 'trace_fb391d76ee98438a9fcfab137d4bf73d', 'trace_53be2c75df5c4fe5866e4d0305a8eed9', 'trace_62dd1e51cd384e13aa67a57afac3d379', 'trace_e7d82bc766a44ee0b6e19a0dfde51f7c', 'trace_4452c43666f949be953e89cf4e1220d1', 'trace_0b254cf3f2e54b5e83cca4db571ef1cc']
- `join-net-revenue` classification=grain; expected_columns=['net_revenue']; observed_columns=['channel_code', 'channel_name', 'net_revenue']; runs=['run_8c0ebb0cba4b44038123e746a12c2938']; trace_ids=['trace_ee2356afec3e4b99bbfa0e5f88c960f4', 'trace_48879f6115f14f1f8e9be394ba757a47', 'trace_63addec1ad7b4a07a0ccc3fa6453b089', 'trace_f14e1896935e47649e667ef6ab45a193', 'trace_c626515fb6a4491f8b7c40c6c0d32751', 'trace_33c86e55a96448309fe12ae363d96d99', 'trace_96b36ee75bce4fe5a2aa78d801906ab4', 'trace_c101c6a6e32940a896c9a58bcb436d10', 'trace_c58ea6dd70e74954abd5435d451980c7']

## Recommended frozen-milestone remediation order

1. **M8** — 35 cases: simple-paid-order-count, simple-pending-order-count, simple-failed-attempts, simple-unit-sales, simple-completed-orders, simple-paid-users, agg-paid-order-channel, agg-paid-acquisition-channel, agg-paid-province, agg-orders-status, agg-gmv-status, agg-attempts-status, agg-refund-status, agg-units-product, agg-units-category, agg-events-name, agg-events-channel, agg-paid-date, agg-orders-date, agg-refunds-date, agg-failed-attempts-date, agg-active-users-province, agg-users-register-date, join-attempts-order, join-units-order, join-units-attempts-order, join-paid-orders-category, join-paid-city, join-events-city, join-units-price-product, join-refunds-order, join-paid-users-channel, empty-future-paid, correction-paid-month, repair-users-province. Unexpected clarification is the dominant multiplier; blocker fields require future non-secret diagnostic capture before remediation.
2. **M9 + M12** — 8 cases: trap-gmv-versus-paid, simple-gmv, simple-paid-amount, simple-payment-attempts, agg-gmv-channel, agg-orders-channel, join-net-revenue, simple-user-count. Verified results with Oracle/public-evidence mismatch require planner-semantic ownership and verification-coverage review.
3. **M13 + M10 + M12** — 4 cases: multiturn-sales, agg-users-province, multiturn-orders, correction-user-grain. Terminal admission/verification repair branches exhausted or were denied.
4. **M14** — 2 cases: agg-users-channel, empty-future-orders. Verified empty/aggregation results failed structured answer synthesis.

## Evidence limitations

- Golden report v0.1 stores trace IDs and payload fingerprints, not trace payloads; the clean reset removed the source run rows before this attribution pass.
- Clarification blocker fields are absent, so no blocker category is inferred from case text.
- Generic pipeline failure codes do not distinguish timeout, output-bound, invalid structured output, and provider failures.
- Same-input standalone M8 replay was not run under the completed large-model environment.
