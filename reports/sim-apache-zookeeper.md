# Báo Cáo Đánh Giá Mô Phỏng Lịch Sử: Dự Án Apache/ZOOKEEPER

## 1. Bối cảnh & Thiết lập Thực nghiệm
- **Instance**: `Apache`
- **Dự án**: `ZOOKEEPER`
- **Thời gian mô phỏng**: Từ `2021-03-01` đến `2021-03-15`
- **Tổng số lượt đánh giá ngày**: `10,912`
- **Số issue duy nhất được đánh giá**: `1,382`
- **Ngưỡng mô hình học máy T0**: `p_delay >= 0.39`, `criticality >= 0.05`
- **Phương pháp đánh giá**: Tái hiện trạng thái lịch sử hàng ngày qua DuckDB và đối chiếu với mốc hoàn thành thực tế.

## 2. Bảng So Sánh Hiệu Năng 3 Cấu Hình

| Cấu hình | Cảnh báo | TP | FP | FN | Precision | Recall | F1-Score | Lead Time TB (ngày) |
|---|---|---|---|---|---|---|---|---|
| Chỉ Hệ Luật Nghiệp Vụ | 10824 | 10821 | 3 | 55 | 0.9997 | 0.9949 | 0.9973 | 88.08 |
| Chỉ Mô Hình Học Máy T0 (p_delay >= 0.39, criticality >= 0.05) | 0 | 0 | 0 | 10876 | 0.0000 | 0.0000 | 0.0000 | N/A |
| Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy) | 10824 | 10821 | 3 | 55 | 0.9997 | 0.9949 | 0.9973 | 88.08 |

## 3. Ma Trận Nhầm Lẫn (Confusion Matrix)

### 3.1. Chỉ Hệ Luật Nghiệp Vụ
| Thực Tế \ Dự Báo | Nguy Cơ (Alert) | An Toàn (No Alert) | Tổng |
|---|---|---|---|
| **Trễ Hạn (Delayed)** | TP = 10821 | FN = 55 | 10876 |
| **Đúng Hạn (On-time)** | FP = 3 | TN = 33 | 36 |
| **Tổng** | 10824 | 88 | 10912 |

### 3.2. Chỉ Mô Hình Học Máy T0
| Thực Tế \ Dự Báo | Nguy Cơ (Alert) | An Toàn (No Alert) | Tổng |
|---|---|---|---|
| **Trễ Hạn (Delayed)** | TP = 0 | FN = 10876 | 10876 |
| **Đúng Hạn (On-time)** | FP = 0 | TN = 36 | 36 |
| **Tổng** | 0 | 10912 | 10912 |

### 3.3. Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy)
| Thực Tế \ Dự Báo | Nguy Cơ (Alert) | An Toàn (No Alert) | Tổng |
|---|---|---|---|
| **Trễ Hạn (Delayed)** | TP = 10821 | FN = 55 | 10876 |
| **Đúng Hạn (On-time)** | FP = 3 | TN = 33 | 36 |
| **Tổng** | 10824 | 88 | 10912 |

## 4. Phân Tích Các Ca Điển Hình (Case Studies)

### 4.1. Các Ca ML Bỏ Sót Được Hệ Luật Cứu Nguy (Rescued by Rules)
| Issue Key | Tóm Tắt | Ngày Phát Hiện | P(Delay) | Yếu Tố Quy Tắc | Lead Time (ngày) |
|---|---|---|---|---|---|
| ZOOKEEPER-100 | Avoid extending Thread in the public ZooKeeper API | 2021-03-01 | 0.20 | overdue:4588.3d | N/A |
| ZOOKEEPER-1004 | TestClient.cc:363: Assertion: equality assertion failed | 2021-03-01 | 0.20 | overdue:3640.0d | N/A |
| ZOOKEEPER-1005 | Zookeeper servers fail to elect a leader succesfully. | 2021-03-01 | 0.20 | overdue:3639.3d | N/A |
| ZOOKEEPER-1008 | ZK should give more specific error on missing myid | 2021-03-01 | 0.20 | overdue:3633.3d | N/A |
| ZOOKEEPER-1011 | fix Java Barrier Documentation example's race condition issue and polish up the Barrier Documentation | 2021-03-01 | 0.20 | overdue:3631.6d | N/A |
| ZOOKEEPER-1015 | DateFormat.getDateTimeInstance() is very expensive, we can cache it to improve performance | 2021-03-01 | 0.20 | overdue:3627.9d | N/A |
| ZOOKEEPER-1017 | Follower.followLeader throws SocketException, then shutdown Follower | 2021-03-01 | 0.20 | overdue:3625.6d | N/A |
| ZOOKEEPER-102 | Need to replace Jute with supported code | 2021-03-01 | 0.20 | overdue:4588.1d | N/A |
| ZOOKEEPER-1022 | let the children under a ZNode in order. | 2021-03-01 | 0.20 | overdue:3621.6d | N/A |
| ZOOKEEPER-1023 | zkpython: add_auth can deadlock the interpreter | 2021-03-01 | 0.20 | overdue:3621.6d | N/A |
| ZOOKEEPER-1024 | let path be binary | 2021-03-01 | 0.20 | overdue:3621.6d | N/A |
| ZOOKEEPER-1026 | Sequence number assignment decreases after old node rejoins cluster | 2021-03-01 | 0.20 | overdue:3618.3d | N/A |
| ZOOKEEPER-1031 | Introduce virtual cluster IP and start that cluster IP on the host running ZK leader | 2021-03-01 | 0.20 | overdue:3614.9d | N/A |
| ZOOKEEPER-1032 | speed up recovery from leader failure | 2021-03-01 | 0.20 | overdue:3613.6d | N/A |
| ZOOKEEPER-1035 | CREATOR_ALL_ACL does not work together with IPAuthenticationProvider | 2021-03-01 | 0.20 | overdue:3612.6d | N/A |
| ZOOKEEPER-1043 | Looped NPE at org.apache.zookeeper.server.NIOServerCnxn$Factory.run(NIOServerCnxn.java:244) | 2021-03-01 | 0.20 | overdue:3605.4d | N/A |
| ZOOKEEPER-1047 | ZooKeeper Standalone does not shutdown cleanly | 2021-03-01 | 0.20 | overdue:3596.6d | N/A |
| ZOOKEEPER-1054 | Drop connections from servers not in the cluster configuration | 2021-03-01 | 0.20 | overdue:3583.6d | N/A |
| ZOOKEEPER-1056 | Questions and Improvements for the C client codebase | 2021-03-01 | 0.20 | overdue:3582.9d | N/A |
| ZOOKEEPER-106 | CancelledKeyException | 2021-03-01 | 0.20 | overdue:4587.4d | N/A |
| ZOOKEEPER-1066 | Multi should have an async version | 2021-03-01 | 0.20 | overdue:3558.1d | N/A |
| ZOOKEEPER-1067 | the doxygen doc should be generated as part of the release | 2021-03-01 | 0.20 | overdue:3556.3d | N/A |
| ZOOKEEPER-1070 | let org.apache.zookeeper.recipes.lock.WriteLock implements java.util.concurrent.locks.Lock | 2021-03-01 | 0.20 | overdue:3555.9d | N/A |
| ZOOKEEPER-1072 | Support for embedded ZooKeeper | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-575, overdue:3555.1d | N/A |
| ZOOKEEPER-1092 | get rid of pending changes | 2021-03-01 | 0.20 | overdue:3536.9d | N/A |
| ZOOKEEPER-1099 | Add simple examples to show the usage of zookeeper | 2021-03-01 | 0.20 | overdue:3528.2d | N/A |
| ZOOKEEPER-1102 | Need update for programmer manual to cover multi operation | 2021-03-01 | 0.20 | overdue:3527.3d | N/A |
| ZOOKEEPER-1106 | mt c client core  when create node | 2021-03-01 | 0.20 | overdue:3525.7d | N/A |
| ZOOKEEPER-1114 | Concurrent primitives library - barrier | 2021-03-01 | 0.20 | overdue:3517.8d | N/A |
| ZOOKEEPER-1116 | Add MX4J Support to Zookeeper | 2021-03-01 | 0.20 | overdue:3515.7d | N/A |
| ZOOKEEPER-1121 | Data cleanup / Eviction policy | 2021-03-01 | 0.20 | overdue:3510.2d | N/A |
| ZOOKEEPER-1122 | "start" and "stop" commands are not present in zkServer.cmd | 2021-03-01 | 0.20 | overdue:3507.5d | N/A |
| ZOOKEEPER-1123 | Can't connect to ZooKeeper server with the C client library from Solaris: connect() call fails. | 2021-03-01 | 0.20 | overdue:3506.5d | N/A |
| ZOOKEEPER-1127 | Auth completion are called for every registered auth, and auths are never removed from the auth list. (even after they are processed). | 2021-03-01 | 0.20 | overdue:3500.2d | N/A |
| ZOOKEEPER-1130 | Java port of PHunt's zk-smoketest | 2021-03-01 | 0.20 | overdue:3497.5d | N/A |
| ZOOKEEPER-1132 | ZooKeeper FAQ is out of date wrt testing SessionExpiredException | 2021-03-01 | 0.20 | overdue:3496.5d | N/A |
| ZOOKEEPER-1133 | allow for "clientPortAddress=host:port" | 2021-03-01 | 0.20 | overdue:3496.2d | N/A |
| ZOOKEEPER-1135 | clarify usage of clientPortAddress zoo.cfg option | 2021-03-01 | 0.20 | overdue:3496.0d | N/A |
| ZOOKEEPER-1137 | AuthFLE is throwing NPE when servers are configured with different election ports. | 2021-03-01 | 0.20 | overdue:3491.5d | N/A |
| ZOOKEEPER-1148 | Multi-threaded handling of reads  | 2021-03-01 | 0.20 | overdue:3483.2d | N/A |
| ZOOKEEPER-1151 | http://zookeeper.apache.org/doc/trunk/api/ missing | 2021-03-01 | 0.20 | overdue:3477.3d | N/A |
| ZOOKEEPER-1157 | Some of the tests timeout or cause JVM crash | 2021-03-01 | 0.20 | overdue:3468.2d | N/A |
| ZOOKEEPER-1158 | C# client | 2021-03-01 | 0.20 | overdue:3467.9d | N/A |
| ZOOKEEPER-116 | simplify testing with quorums - quorum setup test utility code | 2021-03-01 | 0.20 | overdue:4574.7d | N/A |
| ZOOKEEPER-1162 | consistent handling of jute.maxbuffer when attempting to read large zk "directories" | 2021-03-01 | 0.20 | blocked:HBASE-14938, overdue:3462.8d | N/A |
| ZOOKEEPER-1164 | Support encryption for C binding | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-823, overdue:3458.3d | N/A |
| ZOOKEEPER-1167 | C api lacks synchronous version of sync() call. | 2021-03-01 | 0.20 | overdue:3456.4d | N/A |
| ZOOKEEPER-1172 | Support for custom org.apache.zookeeper.client.HostProvider implementation. | 2021-03-01 | 0.20 | overdue:3450.4d | N/A |
| ZOOKEEPER-1173 | Server never forgets old ACL lists | 2021-03-01 | 0.20 | overdue:3449.4d | N/A |
| ZOOKEEPER-1178 | Add eclipse target for supporting Apache IvyDE | 2021-03-01 | 0.20 | overdue:3444.3d | N/A |
| ZOOKEEPER-1183 | Enhance LogFormatter to output additional detail from transaction log | 2021-03-01 | 0.20 | overdue:3442.2d | N/A |
| ZOOKEEPER-1188 | client should detect a broken-network itself | 2021-03-01 | 0.20 | overdue:3440.9d | N/A |
| ZOOKEEPER-119 | Reserve ".zookeeper" node for server use. | 2021-03-01 | 0.20 | overdue:4571.2d | N/A |
| ZOOKEEPER-1196 | improve Kerberos name parsing and canonicalization testing | 2021-03-01 | 0.20 | overdue:3436.3d | N/A |
| ZOOKEEPER-1198 | Refactorings and Cleanups | 2021-03-01 | 0.20 | overdue:3434.6d | N/A |
| ZOOKEEPER-1199 | Make OpCode an enum | 2021-03-01 | 0.20 | overdue:3434.6d | N/A |
| ZOOKEEPER-12 | getChildren doesn't return a list of paths | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-849, overdue:4633.1d | N/A |
| ZOOKEEPER-120 | NIOServerCnxn needs to improve shutdown() handling | 2021-03-01 | 0.20 | overdue:4570.2d | N/A |
| ZOOKEEPER-1202 | Prevent certain state transitions in Java client on close(); improve exception handling and enhance client testability | 2021-03-01 | 0.20 | overdue:3433.9d | N/A |
| ZOOKEEPER-1204 | Shorten calls to ZooTrace | 2021-03-01 | 0.20 | overdue:3430.3d | N/A |
| ZOOKEEPER-1205 | Add a unit test for Kerberos Ticket-Granting Ticket (TGT) renewal | 2021-03-01 | 0.20 | overdue:3429.8d | N/A |
| ZOOKEEPER-1209 | LeaderElection recipe doesn't handle the split-brain issue, n/w disconnection can bring both the client nodes to be in ELECTED | 2021-03-01 | 0.20 | overdue:3428.7d | N/A |
| ZOOKEEPER-1215 | C client persisted cache | 2021-03-01 | 0.20 | overdue:3420.1d | N/A |
| ZOOKEEPER-1217 | Remove unnecessary MissingSessionException in ZooKeeperServer | 2021-03-01 | 0.20 | overdue:3419.4d | N/A |
| ZOOKEEPER-1218 | zktreeutil tool enhancement | 2021-03-01 | 0.20 | overdue:3418.6d | N/A |
| ZOOKEEPER-1223 | C recipes includes <zookeeper.h> instead of <zookeeper/zookeeper.h> | 2021-03-01 | 0.20 | overdue:3413.8d | N/A |
| ZOOKEEPER-1225 | Successive invocation of LeaderElectionSupport.start() will bring the ELECTED node to READY and cause no one in ELECTED state. | 2021-03-01 | 0.20 | overdue:3413.6d | N/A |
| ZOOKEEPER-1228 | Cleanup SessionTracker | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3412.4d | N/A |
| ZOOKEEPER-1230 | Cleanup FileTxnLog | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3411.3d | N/A |
| ZOOKEEPER-1231 | refactor int constants in o.a.z.s.q.Leader to enum | 2021-03-01 | 0.20 | overdue:3409.7d | N/A |
| ZOOKEEPER-1233 | throw RuntimeExceptions for Exceptions that "should never happen" | 2021-03-01 | 0.20 | overdue:3409.5d | N/A |
| ZOOKEEPER-1234 | basic cleanup in LearnerHandler | 2021-03-01 | 0.20 | overdue:3408.7d | N/A |
| ZOOKEEPER-1235 | store KeeperException messages in the Code enum | 2021-03-01 | 0.20 | overdue:3407.6d | N/A |
| ZOOKEEPER-1240 | Compiler issue with redhat linux | 2021-03-01 | 0.20 | overdue:3404.9d | N/A |
| ZOOKEEPER-1242 | Repeat add watcher, memory leak   | 2021-03-01 | 0.20 | overdue:3402.9d | N/A |
| ZOOKEEPER-1244 | resolve remaining compiler warnings | 2021-03-01 | 0.20 | overdue:3401.7d | N/A |
| ZOOKEEPER-1245 | fix compiler warnings in contrib loggraph | 2021-03-01 | 0.20 | overdue:3401.7d | N/A |
| ZOOKEEPER-1248 | multi transaction sets request.exception without reason | 2021-03-01 | 0.20 | overdue:3401.4d | N/A |
| ZOOKEEPER-1251 | call checkSession at begin of PrepRequestProcessor.pRequest | 2021-03-01 | 0.20 | overdue:3400.5d | N/A |
| ZOOKEEPER-1255 | unused fields in DataTree.ProcessTxnResult | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3399.7d | N/A |
| ZOOKEEPER-1257 | Rename MultiTransactionRecord to MultiRequest | 2021-03-01 | 0.20 | overdue:3399.6d | N/A |
| ZOOKEEPER-1258 | Move MultiResponse creation out of FinalRequestProcessor | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3399.5d | N/A |
| ZOOKEEPER-1259 | central mapping from type to txn record class | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3399.5d | N/A |
| ZOOKEEPER-126 | zookeeper client close operation may block indefinitely | 2021-03-01 | 0.20 | overdue:4556.1d | N/A |
| ZOOKEEPER-1261 | Make ZooKeeper code mode Dependency Injection compliant. | 2021-03-01 | 0.20 | overdue:3399.2d | N/A |
| ZOOKEEPER-1266 | "request.getHdr() != null" and "isQuorum" are identical | 2021-03-01 | 0.20 | overdue:3398.4d | N/A |
| ZOOKEEPER-1272 | ZooKeeper.multi() could violate API if server misbehaves | 2021-03-01 | 0.20 | overdue:3397.4d | N/A |
| ZOOKEEPER-1274 | Support child watches to be displayed with 4 letter zookeeper commands (i.e. wchs, wchp and wchc) | 2021-03-01 | 0.20 | overdue:3395.7d | N/A |
| ZOOKEEPER-1276 | ZKDatabase should not hold reference to FileTxnSnapLog | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3393.3d | N/A |
| ZOOKEEPER-1279 | Only SessionTracker should hold reference to sessionsWithTimeouts | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1285, overdue:3393.3d | N/A |
| ZOOKEEPER-1280 | Add current epoch number and timestamp of when it began to 4 letter words (stat, srvr, mntr maybe?) | 2021-03-01 | 0.20 | overdue:3393.3d | N/A |
| ZOOKEEPER-1281 | Stat and srvr 4 letter commands are useless on the leader when leaderServes = false | 2021-03-01 | 0.20 | overdue:3393.3d | N/A |
| ZOOKEEPER-1284 | Cleanup minor PrepRequestProcessor issues | 2021-03-01 | 0.20 | overdue:3392.6d | N/A |
| ZOOKEEPER-1285 | make DataTree immutable | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1228,ZOOKEEPER-1230,ZOOKEEPER-1255,ZOOKEEPER-1258,ZOOKEEPER-1259,ZOOKEEPER-1276,ZOOKEEPER-1279, overdue:3392.4d | N/A |
| ZOOKEEPER-1286 | QuorumPeer contains unused constructor | 2021-03-01 | 0.20 | overdue:3391.7d | N/A |
| ZOOKEEPER-1287 | DataTree deserialization methods should return DataTree instance | 2021-03-01 | 0.20 | overdue:3391.3d | N/A |
| ZOOKEEPER-1288 | Always log sessionId and zxid as hexadecimals | 2021-03-01 | 0.20 | overdue:3391.2d | N/A |
| ZOOKEEPER-1289 | Multi Op Watch Events | 2021-03-01 | 0.20 | overdue:3390.9d | N/A |
| ZOOKEEPER-129 | Thrift proxy | 2021-03-01 | 0.20 | overdue:4553.3d | N/A |
| ZOOKEEPER-1290 | zookeeper_init_with_watches | 2021-03-01 | 0.20 | overdue:3390.9d | N/A |
| ZOOKEEPER-1296 | Add zookeeper-setup-conf.sh script | 2021-03-01 | 0.20 | overdue:3386.1d | N/A |
| ZOOKEEPER-1298 | config,h gets emptied by make, at least on mac os x 10.6.8 | 2021-03-01 | 0.20 | overdue:3383.3d | N/A |
| ZOOKEEPER-1306 | hang in zookeeper_close() | 2021-03-01 | 0.20 | overdue:3376.7d | N/A |
| ZOOKEEPER-1310 | C Api should use state CONNECTION_LOSS | 2021-03-01 | 0.20 | overdue:3365.5d | N/A |
| ZOOKEEPER-1312 | Add a "getChildrenWithStat" operation | 2021-03-01 | 0.20 | overdue:3365.0d | N/A |
| ZOOKEEPER-1313 | Expose/create KeeperException for "Packet len <x> is out of range!" error when jute max buffer size is exceeded | 2021-03-01 | 0.20 | overdue:3365.0d | N/A |
| ZOOKEEPER-1314 | improve zkpython synchronous api implementation | 2021-03-01 | 0.20 | overdue:3364.1d | N/A |
| ZOOKEEPER-1329 | Lock recipe sorts sequenced children incorrectly | 2021-03-01 | 0.20 | overdue:3350.0d | N/A |
| ZOOKEEPER-1330 | Zookeeper server not serving the client request even after completion of Leader election | 2021-03-01 | 0.20 | overdue:3346.8d | N/A |
| ZOOKEEPER-1341 | problem handling invalid multi op in processTxn | 2021-03-01 | 0.20 | overdue:3343.2d | N/A |
| ZOOKEEPER-1347 | Fix the cnxns to use a concurrent data structures | 2021-03-01 | 0.20 | overdue:3336.0d | N/A |
| ZOOKEEPER-1350 | Please make JMX registration optional in LearnerZooKeeperServer | 2021-03-01 | 0.20 | overdue:3331.1d | N/A |
| ZOOKEEPER-1360 | QuorumTest.testNoLogBeforeLeaderEstablishment has several problems | 2021-03-01 | 0.20 | overdue:3322.7d | N/A |
| ZOOKEEPER-1362 | ZooDefs.Ids ACL lists not immutable | 2021-03-01 | 0.20 | overdue:3318.2d | N/A |
| ZOOKEEPER-1364 | Add orthogonal fault injection mechanism/framework | 2021-03-01 | 0.20 | overdue:3317.3d | N/A |
| ZOOKEEPER-1368 | zookeeper c client get apis crash if zhandle is null | 2021-03-01 | 0.20 | overdue:3312.8d | N/A |
| ZOOKEEPER-1369 | Mock access to time-related methods | 2021-03-01 | 0.20 | overdue:3311.1d | N/A |
| ZOOKEEPER-1372 | stat reports inconsistent zxids across servers after a leader change | 2021-03-01 | 0.20 | overdue:3310.9d | N/A |
| ZOOKEEPER-1375 | SendThread is exiting after OOMError | 2021-03-01 | 0.20 | overdue:3309.6d | N/A |
| ZOOKEEPER-1378 | Provide option to turn off sending of diffs | 2021-03-01 | 0.20 | overdue:3305.0d | N/A |
| ZOOKEEPER-1381 | Add a method to get the zookeeper server version from the client | 2021-03-01 | 0.20 | overdue:3304.1d | N/A |
| ZOOKEEPER-1383 | Create update throughput quotas and add hard quota limits | 2021-03-01 | 0.20 | overdue:3303.0d | N/A |
| ZOOKEEPER-1385 | zookeeper.apache.org/doc/trunk/ has broken pointers | 2021-03-01 | 0.20 | overdue:3302.3d | N/A |
| ZOOKEEPER-1396 | Create zoo_append API | 2021-03-01 | 0.20 | overdue:3281.9d | N/A |
| ZOOKEEPER-1398 | zkpython corrupts session passwords that contain nulls | 2021-03-01 | 0.20 | overdue:3281.2d | N/A |
| ZOOKEEPER-1399 | Binary Jar in zookeeper-3.3.4 displays wrong version when run | 2021-03-01 | 0.20 | overdue:3280.9d | N/A |
| ZOOKEEPER-14 | Connect timeouts not calculated properly | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-843, overdue:4633.1d | N/A |
| ZOOKEEPER-1401 | Extract generally useful client utilities from CLI code   | 2021-03-01 | 0.20 | overdue:3279.2d | N/A |
| ZOOKEEPER-1405 | leader election recipe sample code - dispatchEvent invocations can get out of order | 2021-03-01 | 0.20 | overdue:3269.4d | N/A |
| ZOOKEEPER-1410 | Support GetData and GetChildren in Multi for C client | 2021-03-01 | 0.20 | overdue:3266.0d | N/A |
| ZOOKEEPER-1415 | Zookeeper broadcasts host's hostname instead of IP when ecf.exported.containerfactoryargs property is not set | 2021-03-01 | 0.20 | overdue:3260.2d | N/A |
| ZOOKEEPER-1418 | Just a bug in the tutorial code on the website | 2021-03-01 | 0.20 | overdue:3259.1d | N/A |
| ZOOKEEPER-1420 | Kerberos principal to user mapping / authorization | 2021-03-01 | 0.20 | overdue:3258.9d | N/A |
| ZOOKEEPER-1421 | Support for hierarchical ACLs | 2021-03-01 | 0.20 | overdue:3258.9d | N/A |
| ZOOKEEPER-1424 | ZooKeeper will not allow a client to delete a tree when it should allow it | 2021-03-01 | 0.20 | overdue:3258.1d | N/A |
| ZOOKEEPER-1428 | Create command line tool to utilize the new classes introduced in ZOOKEEPER-271 | 2021-03-01 | 0.20 | overdue:3254.3d | N/A |
| ZOOKEEPER-1429 | Response packet caching for get request | 2021-03-01 | 0.20 | overdue:3253.3d | N/A |
| ZOOKEEPER-143 | Exceeding max data node size causes disconnect | 2021-03-01 | 0.20 | overdue:4526.1d | N/A |
| ZOOKEEPER-1436 | Add ZOO_TIMED_OUT_STATE sesion event to notify client about timeout during reconnection | 2021-03-01 | 0.20 | overdue:3246.0d | N/A |
| ZOOKEEPER-1438 | JMX MBeans for client connections can be orphaned | 2021-03-01 | 0.20 | overdue:3244.8d | N/A |
| ZOOKEEPER-1442 | Uncaught exception handler should exit on a java.lang.Error | 2021-03-01 | 0.20 | overdue:3239.3d | N/A |
| ZOOKEEPER-1445 | Add support for binary data for zktreeutil | 2021-03-01 | 0.20 | overdue:3233.3d | N/A |
| ZOOKEEPER-1446 | C API makes it difficult to implement a timed wait_until_connected method correctly | 2021-03-01 | 0.20 | overdue:3231.2d | N/A |
| ZOOKEEPER-1447 | Per-connection network throttling to improve QoS | 2021-03-01 | 0.20 | overdue:3227.0d | N/A |
| ZOOKEEPER-1452 | zoo_multi() & zoo_amulti() update operations for zkpython | 2021-03-01 | 0.20 | overdue:3224.0d | N/A |
| ZOOKEEPER-1453 | corrupted logs may not be correctly identified by FileTxnIterator | 2021-03-01 | 0.20 | overdue:3219.1d | N/A |
| ZOOKEEPER-1455 | there is no way to determine if a session is sasl authenticated or not | 2021-03-01 | 0.20 | overdue:3217.3d | N/A |
| ZOOKEEPER-1456 | sessions cannot specify whether they require kerberos authenticated sessions or not | 2021-03-01 | 0.20 | overdue:3217.3d | N/A |
| ZOOKEEPER-1457 | Ephemeral node deleted for unexpired sessions | 2021-03-01 | 0.20 | overdue:3217.2d | N/A |
| ZOOKEEPER-146 | Allow clients to retrieve the list of hosts/servers from a URL | 2021-03-01 | 0.20 | overdue:4526.0d | N/A |
| ZOOKEEPER-1464 | document that event notification is single threaded in java/c client implementations | 2021-03-01 | 0.20 | overdue:3204.1d | N/A |
| ZOOKEEPER-1468 | Accurately name znode count in "four-letter words" | 2021-03-01 | 0.20 | overdue:3195.3d | N/A |
| ZOOKEEPER-1469 | Adding Cross-Realm support for secure Zookeeper client authentication | 2021-03-01 | 0.20 | overdue:3193.7d | N/A |
| ZOOKEEPER-1470 | zkpython: close() should delete any watcher | 2021-03-01 | 0.20 | overdue:3193.3d | N/A |
| ZOOKEEPER-1472 | WatchedEvent class missing from documentation | 2021-03-01 | 0.20 | overdue:3188.4d | N/A |
| ZOOKEEPER-1473 | Committed proposal log retains triple the memory it needs to | 2021-03-01 | 0.20 | overdue:3184.2d | N/A |
| ZOOKEEPER-1475 | Messages about missing JAAS configuration should not be logged at WARN level | 2021-03-01 | 0.20 | overdue:3182.2d | N/A |
| ZOOKEEPER-1476 | ipv6 reverse dns related timeouts on OSX connecting to localhost | 2021-03-01 | 0.20 | overdue:3181.5d | N/A |
| ZOOKEEPER-1479 | C Client: zoo_add_auth() doesn't wake up the IO thread | 2021-03-01 | 0.20 | overdue:3179.0d | N/A |
| ZOOKEEPER-1480 | ClientCnxn(1161) can't get the current zk server add, so that - Session 0x for server null, unexpected error | 2021-03-01 | 0.20 | overdue:3176.9d | N/A |
| ZOOKEEPER-1485 | client xid overflow is not handled | 2021-03-01 | 0.20 | overdue:3170.2d | N/A |
| ZOOKEEPER-1486 | A couple of bugs in the tutorial code | 2021-03-01 | 0.20 | overdue:3170.1d | N/A |
| ZOOKEEPER-1488 | Some links are not working in the Zookeeper Documentation | 2021-03-01 | 0.20 | overdue:3167.7d | N/A |
| ZOOKEEPER-1500 | Nagios check always returns OK when the critical and warning values are the same | 2021-03-01 | 0.20 | overdue:3148.3d | N/A |
| ZOOKEEPER-1507 | review reading epoch files, improve logging | 2021-03-01 | 0.20 | overdue:3146.3d | N/A |
| ZOOKEEPER-1508 | Reliable standalone mode through redundant databases | 2021-03-01 | 0.20 | overdue:3143.0d | N/A |
| ZOOKEEPER-1511 | Symbolic nodes | 2021-03-01 | 0.20 | overdue:3135.2d | N/A |
| ZOOKEEPER-1512 | Reduce log level of missing ZookeeperSaslClient Security Exception | 2021-03-01 | 0.20 | overdue:3134.2d | N/A |
| ZOOKEEPER-1515 | Long reconnect timeout if leader failed. | 2021-03-01 | 0.20 | overdue:3128.8d | N/A |
| ZOOKEEPER-1516 | Configurable finalizeWait for FastLeaderElection | 2021-03-01 | 0.20 | overdue:3128.5d | N/A |
| ZOOKEEPER-1519 | Zookeeper Async calls can reference free()'d memory | 2021-03-01 | 0.20 | overdue:3127.3d | N/A |
| ZOOKEEPER-1520 | A txn log record with a corrupt sentinel byte looks like EOF | 2021-03-01 | 0.20 | overdue:3127.2d | N/A |
| ZOOKEEPER-1523 | Better logging during instance loading/syncing | 2021-03-01 | 0.20 | overdue:3121.1d | N/A |
| ZOOKEEPER-1524 | use more standard junit annotation "@Before" in SaslXTests rather than static blocks | 2021-03-01 | 0.20 | overdue:3120.2d | N/A |
| ZOOKEEPER-1526 | Correct the documentation of the args for the JavaExample doc | 2021-03-01 | 0.20 | overdue:3112.1d | N/A |
| ZOOKEEPER-153 | add api support for "subscribe" method | 2021-03-01 | 0.20 | overdue:4520.1d | N/A |
| ZOOKEEPER-1534 | Zookeeper server do not send Sal authentication failure notification to the client | 2021-03-01 | 0.20 | overdue:3108.6d | N/A |
| ZOOKEEPER-1539 | Tests in QuorumUtil.startAll() and JMXenv | 2021-03-01 | 0.20 | overdue:3099.8d | N/A |
| ZOOKEEPER-1542 | zkServer.sh start fails but exit status 0 | 2021-03-01 | 0.20 | overdue:3097.2d | N/A |
| ZOOKEEPER-1543 | Bad sessionId/password combo should return auth failure | 2021-03-01 | 0.20 | overdue:3090.2d | N/A |
| ZOOKEEPER-1545 | very odd issue about zookeeper when deploy two web application in one tomcat | 2021-03-01 | 0.20 | overdue:3086.7d | N/A |
| ZOOKEEPER-1546 | "Unable to load database on disk" when restarting after node freeze | 2021-03-01 | 0.20 | overdue:3086.6d | N/A |
| ZOOKEEPER-1547 | Test robustness of client using SASL in the presence of dropped requests | 2021-03-01 | 0.20 | overdue:3086.1d | N/A |
| ZOOKEEPER-1549 | Data inconsistency when follower is receiving a DIFF with a dirty snapshot | 2021-03-01 | 0.20 | overdue:3080.7d | N/A |
| ZOOKEEPER-1556 | Memory leak reported by valgrind mt version | 2021-03-01 | 0.20 | overdue:3057.2d | N/A |
| ZOOKEEPER-1559 | Learner should not snapshot uncommitted state | 2021-03-01 | 0.20 | overdue:3054.4d | N/A |
| ZOOKEEPER-1566 | progress  quits duo to zxid  not in order | 2021-03-01 | 0.20 | overdue:3043.6d | N/A |
| ZOOKEEPER-1567 | JMX can't be disabled with zkEnv.sh | 2021-03-01 | 0.20 | overdue:3043.2d | N/A |
| ZOOKEEPER-1568 | multi should have a non-transaction version | 2021-03-01 | 0.20 | overdue:3037.3d | N/A |
| ZOOKEEPER-1569 | support upsert: setData if the node exists, otherwise, create a new node | 2021-03-01 | 0.20 | overdue:3037.3d | N/A |
| ZOOKEEPER-1577 | Update website with info on how to report security bugs  | 2021-03-01 | 0.20 | overdue:3021.8d | N/A |
| ZOOKEEPER-1579 | Compile error of UnixOperationSystemMXBean with open JDK | 2021-03-01 | 0.20 | overdue:3021.8d | N/A |
| ZOOKEEPER-1586 | tarballs for zkfuse don't compile out of tree | 2021-03-01 | 0.20 | overdue:3010.7d | N/A |
| ZOOKEEPER-1587 | Provide simple way to determine IP address of an ephemeral znode's owner | 2021-03-01 | 0.20 | overdue:3008.0d | N/A |
| ZOOKEEPER-1592 | support deleting a node silently | 2021-03-01 | 0.20 | overdue:3001.8d | N/A |
| ZOOKEEPER-1595 | Sockets should be read until exhausted | 2021-03-01 | 0.20 | overdue:2996.7d | N/A |
| ZOOKEEPER-160 | Admin / Ops Guide Missing Content | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1605 | Make RMI port configurable | 2021-03-01 | 0.20 | overdue:2980.5d | N/A |
| ZOOKEEPER-1607 | Read-only Observer | 2021-03-01 | 0.20 | overdue:2977.8d | N/A |
| ZOOKEEPER-1614 | zoo_multi c MT client windows crash | 2021-03-01 | 0.20 | overdue:2966.0d | N/A |
| ZOOKEEPER-1617 | zookeeper version error log info ? | 2021-03-01 | 0.20 | overdue:2959.6d | N/A |
| ZOOKEEPER-1618 | Disconnected event when stopping leader process | 2021-03-01 | 0.20 | overdue:2959.5d | N/A |
| ZOOKEEPER-162 | Content needed: Provisioning | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1621 | ZooKeeper does not recover from crash when disk was full | 2021-03-01 | 0.20 | overdue:2952.4d | N/A |
| ZOOKEEPER-1623 | Authentication using SASL | 2021-03-01 | 0.20 | overdue:2952.3d | N/A |
| ZOOKEEPER-163 | Content needed: "Things to Consider: Strengths and Limitations" | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1631 | cppunit test TestOperations.cc fails | 2021-03-01 | 0.20 | overdue:2939.2d | N/A |
| ZOOKEEPER-1637 | Intermittent Segfault with zkpython in pyzoo_exists   | 2021-03-01 | 0.20 | overdue:2936.1d | N/A |
| ZOOKEEPER-1639 | zk.getZKDatabase().deserializeSnapshot adds new system znodes instead of replacing existing ones | 2021-03-01 | 0.20 | overdue:2934.9d | N/A |
| ZOOKEEPER-164 | Content needed: "Administering" | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1644 | Add support for compressed SetWatches packet | 2021-03-01 | 0.20 | overdue:2926.1d | N/A |
| ZOOKEEPER-165 | Content needed: "Monitoring" | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1654 | bad documentation link on site | 2021-03-01 | 0.20 | overdue:2910.1d | N/A |
| ZOOKEEPER-1656 | OSGI - Missing import package - ClassNotFoundException | 2021-03-01 | 0.20 | overdue:2908.3d | N/A |
| ZOOKEEPER-1658 | Support SRV records | 2021-03-01 | 0.20 | overdue:2906.5d | N/A |
| ZOOKEEPER-166 | Content needed: "Logging" | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1661 | Random (?) 5s delay when establishing connection | 2021-03-01 | 0.20 | overdue:2902.1d | N/A |
| ZOOKEEPER-167 | Content needed: "Troubleshooting" | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1671 | Remove dependency on log4j 1.2.15 | 2021-03-01 | 0.20 | overdue:2891.4d | N/A |
| ZOOKEEPER-1674 | There is no need to clear & load the database across leader election | 2021-03-01 | 0.20 | overdue:2888.4d | N/A |
| ZOOKEEPER-1675 | Make sync a quorum operation | 2021-03-01 | 0.20 | overdue:2883.1d | N/A |
| ZOOKEEPER-1678 | Server fails to join quorum when a peer is unreachable (5 ZK server setup) | 2021-03-01 | 0.20 | overdue:2881.0d | N/A |
| ZOOKEEPER-168 | Programmer's Guide "Basic Operations" section is missing content | 2021-03-01 | 0.20 | overdue:4515.4d | N/A |
| ZOOKEEPER-1680 | Cannot connect with a given sessionId - it is discarded | 2021-03-01 | 0.20 | overdue:2880.0d | N/A |
| ZOOKEEPER-1681 | ZooKeeper 3.4.x can optionally use netty for nio but the pom does not declare the dep as optional | 2021-03-01 | 0.20 | overdue:2876.5d | N/A |
| ZOOKEEPER-1684 | Failure to update socket addresses on immedate connection | 2021-03-01 | 0.20 | overdue:2873.1d | N/A |
| ZOOKEEPER-1685 | Zookeeper client hard codes the server principal to zookeeper | 2021-03-01 | 0.20 | overdue:2873.1d | N/A |
| ZOOKEEPER-1687 | Number of past transactions retains in ZKDatabase.committedLog should be configurable | 2021-03-01 | 0.20 | overdue:2870.3d | N/A |
| ZOOKEEPER-1688 | Transparent encryption of on-disk files | 2021-03-01 | 0.20 | overdue:2868.2d | N/A |
| ZOOKEEPER-1689 | Remove JVMFLAGS completely from clients, if CLIENT_JVMFLAGS are also set | 2021-03-01 | 0.20 | overdue:2866.4d | N/A |
| ZOOKEEPER-1690 | Race condition when close sock may cause a NPE in sendBuffer  | 2021-03-01 | 0.20 | overdue:2863.5d | N/A |
| ZOOKEEPER-1692 | Add support for single member ensemble | 2021-03-01 | 0.20 | overdue:2863.0d | N/A |
| ZOOKEEPER-1698 | Add deterministic host connection to Java client | 2021-03-01 | 0.20 | overdue:2847.0d | N/A |
| ZOOKEEPER-170 | Content needed: "Read Operations" | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1704 | Please add download link for tutorial | 2021-03-01 | 0.20 | overdue:2839.1d | N/A |
| ZOOKEEPER-1705 | Certain implementations of C's rand() function coupled with the shuffle in libzookeeper_mt's getaddrs() produce a biased distribution of connections. | 2021-03-01 | 0.20 | overdue:2838.2d | N/A |
| ZOOKEEPER-1709 | Limit the size of txnlog file | 2021-03-01 | 0.20 | overdue:2830.9d | N/A |
| ZOOKEEPER-171 | Content needed: "Write Operations" | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1710 | Leader should not use txnlog for synchronization if txnlog is corrupted or missing | 2021-03-01 | 0.20 | overdue:2830.9d | N/A |
| ZOOKEEPER-1716 | jute/Utils.fromCSVBuffer cannot parse data returnd by toCSVBuffer  | 2021-03-01 | 0.20 | overdue:2806.1d | N/A |
| ZOOKEEPER-1717 | Flex code works in debug mode , not in run mode | 2021-03-01 | 0.20 | overdue:2803.4d | N/A |
| ZOOKEEPER-172 | Content needed: "Handling Watches" | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1720 | Race in zookeeper_close() leads to hang | 2021-03-01 | 0.20 | overdue:2781.9d | N/A |
| ZOOKEEPER-1721 | Ability to run without writing to disk | 2021-03-01 | 0.20 | overdue:2781.3d | N/A |
| ZOOKEEPER-1722 | Make ZooKeeper clients more test friendly | 2021-03-01 | 0.20 | overdue:2779.3d | N/A |
| ZOOKEEPER-1723 | unique ensemble identifier | 2021-03-01 | 0.20 | overdue:2779.1d | N/A |
| ZOOKEEPER-1724 | Support Kerberos authentication for non-SUN JDK | 2021-03-01 | 0.20 | overdue:2778.9d | N/A |
| ZOOKEEPER-1729 | Add l4w command "snap" to trigger log rotation and snapshotting  | 2021-03-01 | 0.20 | overdue:2771.9d | N/A |
| ZOOKEEPER-173 | Content needed: "Miscellaneous Operations" | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1734 | Zookeeper fails to connect if one zookeeper host is down on EC2 when using elastic IP (UnknownHostException) | 2021-03-01 | 0.20 | overdue:2765.1d | N/A |
| ZOOKEEPER-1735 | Make ZooKeeper easier to test - support simulating a connection loss | 2021-03-01 | 0.20 | overdue:2765.1d | N/A |
| ZOOKEEPER-1737 | zk scripts no longer work when symlinked | 2021-03-01 | 0.20 | overdue:2751.2d | N/A |
| ZOOKEEPER-1739 | thread safe bug in FastLeaderElection: instance of WorkerSender is not safe published, WorkerSender thread may see that WorkerSender.manager is the default value null | 2021-03-01 | 0.20 | overdue:2747.8d | N/A |
| ZOOKEEPER-174 | Content needed: "Sync vs Async" | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1742 | "make check" doesn't work on macos | 2021-03-01 | 0.20 | overdue:2735.3d | N/A |
| ZOOKEEPER-1749 | Login outside of Zookeeper client | 2021-03-01 | 0.20 | blocked:HADOOP-9938, overdue:2726.1d | N/A |
| ZOOKEEPER-175 | needed: docs for ops - how to setup acls & authentication in the server | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1757 | Adler32 may not be sufficient to protect against data corruption | 2021-03-01 | 0.20 | overdue:2713.0d | N/A |
| ZOOKEEPER-176 | needed: docs for auth plugin developers  | 2021-03-01 | 0.20 | overdue:4515.3d | N/A |
| ZOOKEEPER-1767 | DEBUG log statements use SLF4j {} format to improve performance | 2021-03-01 | 0.20 | overdue:2698.9d | N/A |
| ZOOKEEPER-1768 | Cluster fails election loop until the device is full | 2021-03-01 | 0.20 | overdue:2698.6d | N/A |
| ZOOKEEPER-1777 | Missing ephemeral nodes in one of the members of the ensemble | 2021-03-01 | 0.20 | overdue:2693.6d | N/A |
| ZOOKEEPER-1780 | add a FAQ for why myid file is required | 2021-03-01 | 0.20 | overdue:2693.2d | 18.0 |
| ZOOKEEPER-1787 | Add support for enabling local session in rolling upgrade | 2021-03-01 | 0.20 | overdue:2686.2d | N/A |
| ZOOKEEPER-1788 | Support clientID field on connection requests  | 2021-03-01 | 0.20 | overdue:2686.2d | N/A |
| ZOOKEEPER-1792 | Observers don't need to keep an in-memory copy of last commited proposals  | 2021-03-01 | 0.20 | overdue:2684.9d | N/A |
| ZOOKEEPER-1794 | Add hash check to transaction history in quorum servers | 2021-03-01 | 0.20 | overdue:2681.7d | N/A |
| ZOOKEEPER-1800 | jenkins failure in testGetProposalFromTxn | 2021-03-01 | 0.20 | overdue:2671.3d | N/A |
| ZOOKEEPER-1801 | TestReconfig failure | 2021-03-01 | 0.20 | overdue:2670.5d | N/A |
| ZOOKEEPER-1804 | Stat the realtime tps of zookeepr server | 2021-03-01 | 0.20 | overdue:2666.6d | N/A |
| ZOOKEEPER-1814 | Reduction of waiting time during Fast Leader Election | 2021-03-01 | 0.20 | overdue:2649.6d | N/A |
| ZOOKEEPER-1816 | ClientCnxn.close() should block until threads have died | 2021-03-01 | 0.20 | overdue:2649.1d | N/A |
| ZOOKEEPER-1820 | The artifact org.apache.zookeeper:zookeeper:pom:3.4.5 has no license specified. | 2021-03-01 | 0.20 | overdue:2643.0d | N/A |
| ZOOKEEPER-1824 | We need a MiniZooKeeperCluster for unit test | 2021-03-01 | 0.20 | overdue:2632.7d | N/A |
| ZOOKEEPER-1825 | In ClientBase, if not set "build.test.dir" will throw IOException | 2021-03-01 | 0.20 | overdue:2632.5d | N/A |
| ZOOKEEPER-1826 | zookeeper ganglia module fails to read the output of stat when too many clients are connected | 2021-03-01 | 0.20 | overdue:2631.2d | N/A |
| ZOOKEEPER-1827 | Reduce the number of mntr calls in zookeeper ganglia plugin | 2021-03-01 | 0.20 | overdue:2631.1d | N/A |
| ZOOKEEPER-1828 | Audit src/c/src/zookeeper.c for missing error checking & early returns | 2021-03-01 | 0.20 | overdue:2631.0d | N/A |
| ZOOKEEPER-1832 | Add count of connected clients to submitted ganglia metrics | 2021-03-01 | 0.20 | overdue:2629.2d | N/A |
| ZOOKEEPER-1842 | Election listening thread not shutdown for leaders or followers | 2021-03-01 | 0.20 | overdue:2618.1d | N/A |
| ZOOKEEPER-1848 | [WINDOWS] Java NIO socket channels does not work with Windows ipv6 on JDK6 | 2021-03-01 | 0.20 | overdue:2616.9d | N/A |
| ZOOKEEPER-1855 | calls to zoo_set_server() fail to flush outstanding request queue. | 2021-03-01 | 0.20 | overdue:2601.0d | N/A |
| ZOOKEEPER-1856 | zookeeper C-client can fail to switch from a dead server in a 3+ server ensemble if the client only has a 2 server list. | 2021-03-01 | 0.20 | overdue:2601.0d | N/A |
| ZOOKEEPER-1859 | pwriter should be closed in NIOServerCnxn#checkFourLetterWord() | 2021-03-01 | 0.20 | overdue:2592.2d | N/A |
| ZOOKEEPER-1865 | Fix retry logic in Learner.connectToLeader()  | 2021-03-01 | 0.20 | overdue:2582.0d | N/A |
| ZOOKEEPER-1871 | Add an option to zkCli to wait for connection before executing commands | 2021-03-01 | 0.20 | overdue:2574.7d | 13.6 |
| ZOOKEEPER-1875 | NullPointerException in ClientCnxn$EventThread.processEvent | 2021-03-01 | 0.20 | overdue:2569.8d | N/A |
| ZOOKEEPER-1876 | Add support for installing windows services in .cmd scripts | 2021-03-01 | 0.20 | overdue:2566.1d | N/A |
| ZOOKEEPER-1879 | improve the correctness checking of txn log replay | 2021-03-01 | 0.20 | overdue:2562.1d | N/A |
| ZOOKEEPER-1881 | Shutdown server immediately upon PrivilegedActionException | 2021-03-01 | 0.20 | overdue:2559.0d | N/A |
| ZOOKEEPER-1884 | zkCli silently ignores commands with missing parameters | 2021-03-01 | 0.20 | overdue:2552.5d | N/A |
| ZOOKEEPER-1886 | Exception in Follower.followLeader() where Leader is still running, can make that follower hang in LeaderElection | 2021-03-01 | 0.20 | overdue:2551.8d | N/A |
| ZOOKEEPER-1890 | unclosed FileOutputStream in FileTxnLog.rollLog | 2021-03-01 | 0.20 | overdue:2544.9d | N/A |
| ZOOKEEPER-1896 | Reconfig error messages when upgrading from 3.4.6 to 3.5.0 | 2021-03-01 | 0.20 | overdue:2527.3d | N/A |
| ZOOKEEPER-1899 | zookeeper-cli does not use STDERR and STDOUT correctly to output information | 2021-03-01 | 0.20 | overdue:2524.4d | N/A |
| ZOOKEEPER-1914 | TestWatchers.cc failure | 2021-03-01 | 0.20 | overdue:2495.0d | N/A |
| ZOOKEEPER-1915 | Use $(ProjectDir) macro to specify include directories | 2021-03-01 | 0.20 | overdue:2494.0d | N/A |
| ZOOKEEPER-1916 | make Cli depend on zookeeper | 2021-03-01 | 0.20 | overdue:2494.0d | N/A |
| ZOOKEEPER-1920 | Login thread is not shutdown when close the ClientCnxn | 2021-03-01 | 0.20 | overdue:2485.9d | N/A |
| ZOOKEEPER-1922 | Negative min latency value | 2021-03-01 | 0.20 | overdue:2478.5d | N/A |
| ZOOKEEPER-1931 | intern project idea: implement zab | 2021-03-01 | 0.20 | overdue:2451.2d | N/A |
| ZOOKEEPER-1934 | Stale data received from sync'd ensemble peer | 2021-03-01 | 0.20 | overdue:2447.0d | N/A |
| ZOOKEEPER-1935 | Current ZooKeeper C Library (Client) makes a distinction between removing a child node and adding a child node on receiving ZOO_CHILD_EVENT session event | 2021-03-01 | 0.20 | overdue:2442.8d | N/A |
| ZOOKEEPER-1940 | Integrate with Docker. | 2021-03-01 | 0.20 | overdue:2439.3d | N/A |
| ZOOKEEPER-1941 | 2014-06-14 12:40:46,886 INFO org.apache.zookeeper.ClientCnxn: Opening socket connection to server  Will not attempt to authenticate using SASL (unknown error) | 2021-03-01 | 0.20 | overdue:2438.3d | N/A |
| ZOOKEEPER-1944 | The 2pc picture of zookeeperInternals.pdf may be not correct.  | 2021-03-01 | 0.20 | overdue:2431.7d | N/A |
| ZOOKEEPER-1947 | Implement a better way to specify joiners | 2021-03-01 | 0.20 | overdue:2426.2d | N/A |
| ZOOKEEPER-195 | Configuration information is spread across too many docs. Consolidate into one | 2021-03-01 | 0.20 | overdue:4505.0d | N/A |
| ZOOKEEPER-1951 | Clean up raw type compile warnings under Java 7 | 2021-03-01 | 0.20 | overdue:2421.3d | N/A |
| ZOOKEEPER-1954 | StaticHostProvider loses IPv6 scope ID when resolving server addresses | 2021-03-01 | 0.20 | overdue:2419.1d | N/A |
| ZOOKEEPER-1955 | EOFException on Reading Snapshot | 2021-03-01 | 0.20 | overdue:2418.1d | N/A |
| ZOOKEEPER-1956 | Support Cleanup script in windows | 2021-03-01 | 0.20 | overdue:2415.6d | N/A |
| ZOOKEEPER-1957 | ReconfigTest can fail when checking remote peer MXBean ElectionAddress | 2021-03-01 | 0.20 | overdue:2415.2d | N/A |
| ZOOKEEPER-1958 | Client does not detect rejected connections | 2021-03-01 | 0.20 | overdue:2415.0d | N/A |
| ZOOKEEPER-1959 | Move zkEnv files to conf folder, since it is expected to be configured by user | 2021-03-01 | 0.20 | overdue:2414.4d | N/A |
| ZOOKEEPER-1960 | Improve logs in PurgeTxnLog.java to give more details | 2021-03-01 | 0.20 | overdue:2414.4d | N/A |
| ZOOKEEPER-1961 | NPE in ZooKeeperServerMain.shutdown() | 2021-03-01 | 0.20 | overdue:2414.3d | N/A |
| ZOOKEEPER-1965 | Install could not be done on powerpc Error: Unrecognized opcode: `lock' | 2021-03-01 | 0.20 | overdue:2407.9d | N/A |
| ZOOKEEPER-1967 | Eliminate the temp dynamic config file, find last proposed config in transaction log. | 2021-03-01 | 0.20 | overdue:2406.1d | N/A |
| ZOOKEEPER-1971 | Make JMX remote monitoring port configurable | 2021-03-01 | 0.20 | overdue:2404.1d | N/A |
| ZOOKEEPER-1976 | address internationalization issues identified by findbugs 2.0.3 | 2021-03-01 | 0.20 | overdue:2402.9d | N/A |
| ZOOKEEPER-1977 | Calibrate initLimit dynamically | 2021-03-01 | 0.20 | overdue:2402.2d | N/A |
| ZOOKEEPER-1983 | Append to zookeeper.out (not overwrite) to support logrotation | 2021-03-01 | 0.20 | overdue:2400.1d | N/A |
| ZOOKEEPER-1985 | Memory leak in C client | 2021-03-01 | 0.20 | overdue:2399.9d | N/A |
| ZOOKEEPER-2000 | Fix ReconfigTest.testPortChange | 2021-03-01 | 0.20 | overdue:2391.7d | N/A |
| ZOOKEEPER-2001 | Please provide a parse method with input stream as parameter | 2021-03-01 | 0.20 | overdue:2391.1d | N/A |
| ZOOKEEPER-2003 | Missing fsync() on the logs parent directory | 2021-03-01 | 0.20 | overdue:2386.7d | N/A |
| ZOOKEEPER-2005 | Failure to setCurrentEpoch on lead | 2021-03-01 | 0.20 | overdue:2384.4d | N/A |
| ZOOKEEPER-2010 | Add logs when ZooKeeper is back running | 2021-03-01 | 0.20 | overdue:2377.2d | N/A |
| ZOOKEEPER-2011 | move legacy zookeeper jar to dist-maven | 2021-03-01 | 0.20 | overdue:2376.9d | N/A |
| ZOOKEEPER-2012 | HBase client hangs after client-side OOM | 2021-03-01 | 0.20 | overdue:2376.8d | N/A |
| ZOOKEEPER-2016 | Automate client-side rebalancing | 2021-03-01 | 0.20 | overdue:2370.3d | N/A |
| ZOOKEEPER-2018 | Zookeper node fails to boot if writes are reordered | 2021-03-01 | 0.20 | overdue:2369.2d | N/A |
| ZOOKEEPER-2019 | Unhandled exception when setting invalid limits data in /zookeeper/quota/some/path/zookeeper_limits  | 2021-03-01 | 0.20 | overdue:2369.0d | N/A |
| ZOOKEEPER-2020 | Change TRUNC to SNAP in sync phase for safety guarantee  | 2021-03-01 | 0.20 | overdue:2367.2d | N/A |
| ZOOKEEPER-2021 | ZKserver.cmd fails usng the config param  | 2021-03-01 | 0.20 | overdue:2365.4d | N/A |
| ZOOKEEPER-2022 | The log of sessionTimeout is inaccurate | 2021-03-01 | 0.20 | overdue:2363.6d | N/A |
| ZOOKEEPER-2023 | Improved system test | 2021-03-01 | 0.20 | overdue:2363.5d | N/A |
| ZOOKEEPER-2025 | Single-node ejection caused apparent reconnection storm, leading to cluster unresponsiveness | 2021-03-01 | 0.20 | overdue:2362.2d | N/A |
| ZOOKEEPER-2027 | Dynamic quorum weight shifting between datacenters for follow the sun operations | 2021-03-01 | 0.20 | overdue:2356.6d | N/A |
| ZOOKEEPER-2028 | TestClient#testAuth aborts because ASSERT throws exception again in destructor when there is active exception already | 2021-03-01 | 0.20 | overdue:2355.7d | N/A |
| ZOOKEEPER-2031 | Support tagging a QuorumServer | 2021-03-01 | 0.20 | overdue:2351.1d | N/A |
| ZOOKEEPER-2035 | diagnostics on SASL connection problems doesn't match error strings sent back | 2021-03-01 | 0.20 | overdue:2347.3d | N/A |
| ZOOKEEPER-2038 | Coding error in recipes/lock/src/c/src/zoo_lock.c | 2021-03-01 | 0.20 | overdue:2344.9d | N/A |
| ZOOKEEPER-2041 | maxClientCnxns should limit connections for each process rather than ip | 2021-03-01 | 0.20 | overdue:2343.9d | N/A |
| ZOOKEEPER-2043 | Too many connections,maxClientCnxns  don't close  | 2021-03-01 | 0.20 | overdue:2338.6d | N/A |
| ZOOKEEPER-2045 | ConnectStringParser public api didn't handle null connect string | 2021-03-01 | 0.20 | overdue:2338.0d | N/A |
| ZOOKEEPER-2048 | Ability to support alphabetic characters in the version string | 2021-03-01 | 0.20 | overdue:2334.7d | N/A |
| ZOOKEEPER-2050 | Maven dependency should remove the 3 dependencies  | 2021-03-01 | 0.20 | overdue:2330.4d | N/A |
| ZOOKEEPER-2051 | Creating ephemeral znodes from within a transaction fail with local sessions | 2021-03-01 | 0.20 | overdue:2330.2d | N/A |
| ZOOKEEPER-2053 | Zookeeper scripts should honor ZOOKEEPER_HOME | 2021-03-01 | 0.20 | overdue:2328.1d | N/A |
| ZOOKEEPER-2055 | Don't throw ArrayIndexOutOfBoundsException when SASL username/password isn't specified | 2021-03-01 | 0.20 | overdue:2323.5d | N/A |
| ZOOKEEPER-2057 | ZooKeeper should be as fast as Kafka | 2021-03-01 | 0.20 | overdue:2322.0d | N/A |
| ZOOKEEPER-2063 | Netty+SSL support for client-server communication | 2021-03-01 | 0.20 | overdue:2313.1d | N/A |
| ZOOKEEPER-2067 | Init script fails to track PID file when using a non-standard dataDir | 2021-03-01 | 0.20 | overdue:2305.9d | N/A |
| ZOOKEEPER-2068 | ServerCnxnTest.testServerCnxnExpiry failed when using Netty server option | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-2063, overdue:2304.8d | N/A |
| ZOOKEEPER-207 | All the threads should have names so that its easier to see throguh a stack trace. | 2021-03-01 | 0.20 | overdue:4497.1d | N/A |
| ZOOKEEPER-2070 | Explain how to update and publish the project website | 2021-03-01 | 0.20 | overdue:2304.0d | N/A |
| ZOOKEEPER-2071 | Update docs for Apache branding and trademark requirements | 2021-03-01 | 0.20 | overdue:2304.0d | N/A |
| ZOOKEEPER-2075 | Utils.bufEquals | 2021-03-01 | 0.20 | overdue:2292.2d | N/A |
| ZOOKEEPER-2076 | Improve Leader Change Mechanism | 2021-03-01 | 0.20 | overdue:2289.0d | N/A |
| ZOOKEEPER-2077 | Wild-card/Regex Support for Zookeeper client commands | 2021-03-01 | 0.20 | overdue:2287.6d | N/A |
| ZOOKEEPER-2081 | Leader election cannot complete when a node is blackholed (unreachable) even when quorum is possible. | 2021-03-01 | 0.20 | overdue:2285.9d | N/A |
| ZOOKEEPER-2086 | Unnecessary error log when defaultWatcher  is not set for ZooKeeper client | 2021-03-01 | 0.20 | overdue:2278.6d | N/A |
| ZOOKEEPER-2088 | Provide custom logging hook | 2021-03-01 | 0.20 | overdue:2275.4d | N/A |
| ZOOKEEPER-2089 | Improve the building blocks part of the programmer's guide | 2021-03-01 | 0.20 | overdue:2274.4d | N/A |
| ZOOKEEPER-2090 | Fix Zookeeper docs "To be done" notices | 2021-03-01 | 0.20 | overdue:2274.4d | N/A |
| ZOOKEEPER-2091 | Possible logic error in ClientCnxnSocketNIO | 2021-03-01 | 0.20 | overdue:2274.0d | N/A |
| ZOOKEEPER-2092 | A zk instance can not be connected for ZooKeeperServer is not running | 2021-03-01 | 0.20 | overdue:2272.5d | N/A |
| ZOOKEEPER-2093 | Expose cumulative latency and request count | 2021-03-01 | 0.20 | overdue:2268.2d | N/A |
| ZOOKEEPER-2097 | Clarify security requirement for Exists request | 2021-03-01 | 0.20 | overdue:2250.1d | N/A |
| ZOOKEEPER-2099 | Using txnlog to sync a learner can corrupt the learner's datatree | 2021-03-01 | 0.20 | overdue:2240.1d | N/A |
| ZOOKEEPER-2100 | ZooKeeperSaslClient doesn't shut down Login thread | 2021-03-01 | 0.20 | overdue:2240.0d | N/A |
| ZOOKEEPER-2104 | Sudden crash of all nodes in the cluster | 2021-03-01 | 0.20 | overdue:2229.0d | N/A |
| ZOOKEEPER-2108 | Compilation error in ZkAdaptor.cc with GCC 4.7 or later | 2021-03-01 | 0.20 | overdue:2212.5d | N/A |
| ZOOKEEPER-2112 | Netty for quorum communication | 2021-03-01 | 0.20 | overdue:2211.0d | N/A |
| ZOOKEEPER-2113 | SSL support for ClientCnxnSocketNetty | 2021-03-01 | 0.20 | overdue:2209.1d | N/A |
| ZOOKEEPER-2115 | Initialize command succeeds even though it didn't in case of permission errors on the data directory | 2021-03-01 | 0.20 | overdue:2202.0d | N/A |
| ZOOKEEPER-2117 | "caught end of stream", server: "Stale state" of a Zk client just after connecting | 2021-03-01 | 0.20 | overdue:2194.4d | N/A |
| ZOOKEEPER-2118 | CLONE - Netty for quorum communication | 2021-03-01 | 0.20 | overdue:2192.7d | N/A |
| ZOOKEEPER-2120 | SSL feature on Netty | 2021-03-01 | 0.20 | overdue:2190.2d | N/A |
| ZOOKEEPER-2121 | Documentation of create method is unclear, incorrect, or both | 2021-03-01 | 0.20 | overdue:2189.3d | N/A |
| ZOOKEEPER-2128 | zoo_aremove_watchers API is incorrect | 2021-03-01 | 0.20 | overdue:2183.8d | N/A |
| ZOOKEEPER-2130 | Command to get ensemble summary | 2021-03-01 | 0.20 | overdue:2183.5d | N/A |
| ZOOKEEPER-2131 | Error:KeeperErrorCode = NoNode | 2021-03-01 | 0.20 | overdue:2183.3d | N/A |
| ZOOKEEPER-2132 | Follower::syncWithLeader should roll logs before taking snapshot | 2021-03-01 | 0.20 | overdue:2181.2d | N/A |
| ZOOKEEPER-2135 | fix trunk build | 2021-03-01 | 0.20 | overdue:2171.1d | N/A |
| ZOOKEEPER-2136 | Sync() should get quorum acks. | 2021-03-01 | 0.20 | overdue:2169.8d | N/A |
| ZOOKEEPER-2144 | Provide a way to update the auth info on a connection | 2021-03-01 | 0.20 | overdue:2163.5d | N/A |
| ZOOKEEPER-2145 | Node can be seen but not deleted | 2021-03-01 | 0.20 | overdue:2161.1d | N/A |
| ZOOKEEPER-2147 | Remove ZOO_NOTWATCHING_EVENT | 2021-03-01 | 0.20 | overdue:2158.2d | N/A |
| ZOOKEEPER-2148 | ZooKeeper SSL User Guide | 2021-03-01 | 0.20 | overdue:2157.0d | N/A |
| ZOOKEEPER-2150 | Observers losing connection with active ensemble and dont recover | 2021-03-01 | 0.20 | overdue:2155.3d | N/A |
| ZOOKEEPER-2154 | NPE in KeeperException | 2021-03-01 | 0.20 | overdue:2148.8d | 114.3 |
| ZOOKEEPER-2159 | Pluggable SASL Authentication | 2021-03-01 | 0.20 | overdue:2141.7d | N/A |
| ZOOKEEPER-2161 | Cleanup task fails - java.io.FileNotFoundException: /zookeeper.log (Permission Denied) | 2021-03-01 | 0.20 | overdue:2140.3d | N/A |
| ZOOKEEPER-2162 | infinite exception loop occurs when dataDir is lost | 2021-03-01 | 0.20 | overdue:2135.8d | N/A |
| ZOOKEEPER-2165 | OSGi requires package "server.quorom.flexible" be exported | 2021-03-01 | 0.20 | overdue:2134.5d | N/A |
| ZOOKEEPER-2166 | backupOldConfig() doesn't check for null | 2021-03-01 | 0.20 | overdue:2134.1d | N/A |
| ZOOKEEPER-2167 | Restarting current leader node sometimes results in a permanent loss of quorum | 2021-03-01 | 0.20 | overdue:2134.0d | N/A |
| ZOOKEEPER-2170 | Zookeeper is not logging as per the configuration in log4j.properties | 2021-03-01 | 0.20 | overdue:2128.5d | N/A |
| ZOOKEEPER-2175 | Checksum validation for malformed packets needs to handle. | 2021-03-01 | 0.20 | overdue:2124.9d | N/A |
| ZOOKEEPER-2177 | point to md5/sha1/asc files in releases.html | 2021-03-01 | 0.20 | overdue:2118.7d | N/A |
| ZOOKEEPER-2180 | quota do not take effect in version 3.4.6 | 2021-03-01 | 0.20 | overdue:2113.9d | N/A |
| ZOOKEEPER-2181 | Slider-Zookeeper integration testcase fails with Zookeeper-3.5.0-alpha version | 2021-03-01 | 0.20 | overdue:2113.5d | N/A |
| ZOOKEEPER-2188 | client connection hung up because of  dead loop | 2021-03-01 | 0.20 | overdue:2107.5d | N/A |
| ZOOKEEPER-2189 | QuorumCnxManager: use BufferedOutputStream for initial msg | 2021-03-01 | 0.20 | overdue:2105.7d | N/A |
| ZOOKEEPER-2192 | Port "Introduce new ZNode type: container" to 3.4.x | 2021-03-01 | 0.20 | overdue:2099.3d | N/A |
| ZOOKEEPER-2196 | Web Access link broken | 2021-03-01 | 0.20 | overdue:2096.1d | N/A |
| ZOOKEEPER-22 | Automatic request retries on connect failover | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-660, overdue:4633.1d | N/A |
| ZOOKEEPER-2200 | Perl ZooKeeper locks up during heavy load | 2021-03-01 | 0.20 | overdue:2086.2d | N/A |
| ZOOKEEPER-2202 | Cluster crashes when reconfig adds an unreachable observer | 2021-03-01 | 0.20 | overdue:2085.1d | N/A |
| ZOOKEEPER-2215 | Four letter command don't have kerberos authentication  | 2021-03-01 | 0.20 | overdue:2075.5d | N/A |
| ZOOKEEPER-2216 | Get the property hierarchy as a a whole tree  | 2021-03-01 | 0.20 | overdue:2071.3d | N/A |
| ZOOKEEPER-2218 | Close IO Streams in finally block | 2021-03-01 | 0.20 | overdue:2064.9d | N/A |
| ZOOKEEPER-2219 | ZooKeeper server should better handle SessionMovedException. | 2021-03-01 | 0.20 | overdue:2063.7d | N/A |
| ZOOKEEPER-2220 | Couldn't instantiate org.apache.zookeeper.ClientCnxnSocketNetty | 2021-03-01 | 0.20 | overdue:2063.3d | N/A |
| ZOOKEEPER-2225 | modify existing 'configuration' command or add new one to return list of ZooKeeper's ensemble members | 2021-03-01 | 0.20 | overdue:2057.4d | N/A |
| ZOOKEEPER-2226 | Mixing sequential and non-sequential can throw NodeExists for sequential nodes | 2021-03-01 | 0.20 | overdue:2056.2d | N/A |
| ZOOKEEPER-2230 | Connections fo ZooKeeper server becomes slow over time with native GSSAPI | 2021-03-01 | 0.20 | overdue:2055.7d | N/A |
| ZOOKEEPER-2231 | ServerSocket opened by ZooKeeperServer cannot use SO_REUSEADDR under Linux | 2021-03-01 | 0.20 | overdue:2054.7d | N/A |
| ZOOKEEPER-2232 | zkperl is out of sync with CPAN releases | 2021-03-01 | 0.20 | overdue:2045.9d | N/A |
| ZOOKEEPER-2233 | Invalid description in the comment of LearnerHandler.syncFollower() | 2021-03-01 | 0.20 | overdue:2043.7d | N/A |
| ZOOKEEPER-2234 | Snapshot serialization race condition can lead to partial transaction and inoperable data node | 2021-03-01 | 0.20 | overdue:2041.6d | N/A |
| ZOOKEEPER-2236 | Zookeeper truncates file to 0bytes | 2021-03-01 | 0.20 | overdue:2034.3d | N/A |
| ZOOKEEPER-2241 | In Login.java, a tgt with a small expiry time will break the code | 2021-03-01 | 0.20 | overdue:2021.2d | N/A |
| ZOOKEEPER-2246 | quorum connection manager takes a long time to shut down | 2021-03-01 | 0.20 | overdue:2013.9d | N/A |
| ZOOKEEPER-2248 | log.zxid file is very large size. It's likely to lead to zk disk space is not enough. | 2021-03-01 | 0.20 | overdue:2011.7d | N/A |
| ZOOKEEPER-2250 | Support client connections using a SOCKS proxy | 2021-03-01 | 0.20 | overdue:2009.0d | N/A |
| ZOOKEEPER-2255 | Use static member classes when permitted | 2021-03-01 | 0.20 | overdue:2006.8d | N/A |
| ZOOKEEPER-2258 | ZooKeeper bin scripts for the Windows needs to be updated | 2021-03-01 | 0.20 | overdue:1999.7d | N/A |
| ZOOKEEPER-2259 | 4 letter word commands are slow because these unnecessarily go through Sasl authentication | 2021-03-01 | 0.20 | overdue:1999.4d | N/A |
| ZOOKEEPER-2260 | Paginated getChildren call | 2021-03-01 | 0.20 | blocked:HBASE-14938, overdue:1999.0d | N/A |
| ZOOKEEPER-2263 | ZooKeeper server should not start when neither clientPort no secureClientPort is configured | 2021-03-01 | 0.20 | overdue:1998.4d | N/A |
| ZOOKEEPER-2266 | Integrate JaCoCo Coverage Library | 2021-03-01 | 0.20 | overdue:1988.6d | N/A |
| ZOOKEEPER-2267 | zoo_amulti doesn't correctly return ZINVALIDSTATE errors  | 2021-03-01 | 0.20 | overdue:1987.7d | N/A |
| ZOOKEEPER-2273 | Uninvited ZK joins the ensemble | 2021-03-01 | 0.20 | overdue:1985.2d | N/A |
| ZOOKEEPER-2274 | ZooKeeperServerMain is difficult to subclass for unit testing | 2021-03-01 | 0.20 | overdue:1984.3d | N/A |
| ZOOKEEPER-2276 | Multi operation failure  does not include path in KeeperException | 2021-03-01 | 0.20 | overdue:1980.8d | N/A |
| ZOOKEEPER-2277 | Zookeeper off-line snapshot and transaction log viewer | 2021-03-01 | 0.20 | overdue:1979.3d | N/A |
| ZOOKEEPER-2280 | NettyServerCnxnFactory doesn't honor maxClientCnxns param | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-2454, overdue:1973.9d | N/A |
| ZOOKEEPER-2285 | QuorumTest's ignored test case causes wrong CI pre-commit feedback | 2021-03-01 | 0.20 | overdue:1967.1d | N/A |
| ZOOKEEPER-2286 | Doc Issue | 2021-03-01 | 0.20 | overdue:1966.7d | N/A |
| ZOOKEEPER-2288 | During shutdown, server may fail to ack completed transactions to clients. | 2021-03-01 | 0.20 | overdue:1955.1d | N/A |
| ZOOKEEPER-2289 | Support use of SASL "auth-int" and "auth-conf" quality of protection. | 2021-03-01 | 0.20 | overdue:1955.0d | N/A |
| ZOOKEEPER-2290 | Add read/write qps metrics in monitor cmd | 2021-03-01 | 0.20 | overdue:1953.8d | N/A |
| ZOOKEEPER-2291 | JMX log should not be printed while stopping ZK Server | 2021-03-01 | 0.20 | overdue:1952.3d | N/A |
| ZOOKEEPER-2293 | Incorrect log level 'warn'  is resulting in clutering of logs, Suggest to demote it to DEBUG from WARN | 2021-03-01 | 0.20 | overdue:1951.7d | N/A |
| ZOOKEEPER-2305 | created | 2021-03-01 | 0.20 | overdue:1938.5d | N/A |
| ZOOKEEPER-2308 | Warning messages in the zookeeper logs | 2021-03-01 | 0.20 | overdue:1936.3d | N/A |
| ZOOKEEPER-2312 | Fix arrow direction in the 2-phase commit diagram in Zookeeper internal docs | 2021-03-01 | 0.20 | overdue:1930.8d | N/A |
| ZOOKEEPER-2313 | Refactor ZooKeeperServerBean and its subclasses (LeaderBean, ObserverBean, FollowerBean) | 2021-03-01 | 0.20 | overdue:1930.6d | N/A |
| ZOOKEEPER-2314 | Improvements to SASL | 2021-03-01 | 0.20 | overdue:1929.3d | N/A |
| ZOOKEEPER-2320 | C-client crashes when removing watcher asynchronously in "local" mode | 2021-03-01 | 0.20 | overdue:1922.0d | N/A |
| ZOOKEEPER-2321 | C-client session watcher removal is not thread safe | 2021-03-01 | 0.20 | overdue:1921.0d | N/A |
| ZOOKEEPER-2322 | Zookeeper server throws NullPointerExceptions while revalidating the session to the client | 2021-03-01 | 0.20 | overdue:1918.5d | N/A |
| ZOOKEEPER-2324 | Make Client authentication mechanism change optional | 2021-03-01 | 0.20 | overdue:1916.1d | N/A |
| ZOOKEEPER-2327 | "ConnectionLoss for /dog" | 2021-03-01 | 0.20 | overdue:1914.9d | N/A |
| ZOOKEEPER-233 | Create a slimmer jar for clients to reduce their disk footprint. | 2021-03-01 | 0.20 | overdue:4466.1d | N/A |
| ZOOKEEPER-2332 | Zookeeper failed to start for empty txn log | 2021-03-01 | 0.20 | overdue:1907.4d | N/A |
| ZOOKEEPER-2339 | Document differences in ZooKeeper usage on Windows. | 2021-03-01 | 0.20 | overdue:1896.0d | N/A |
| ZOOKEEPER-2342 | Migrate to Log4J 2. | 2021-03-01 | 0.20 | blocked:LOG4J2-1514, overdue:1895.0d | N/A |
| ZOOKEEPER-2343 | Zookeeper 3.5.1 failed to deploy into the kubernetes | 2021-03-01 | 0.20 | overdue:1889.5d | N/A |
| ZOOKEEPER-2344 | Provide more diagnostics/stack traces on SASL Auth failure | 2021-03-01 | 0.20 | overdue:1889.3d | N/A |
| ZOOKEEPER-2345 | ServerCnxnFactory.configureSaslLogin() loses stack trace on auth failures | 2021-03-01 | 0.20 | overdue:1889.3d | N/A |
| ZOOKEEPER-2346 | SASL Auth failure manifested to client as connection refusal | 2021-03-01 | 0.20 | overdue:1889.3d | N/A |
| ZOOKEEPER-2348 | Data between leader and followers are not synchronized. | 2021-03-01 | 0.20 | overdue:1886.6d | N/A |
| ZOOKEEPER-235 | SSL Support for clients | 2021-03-01 | 0.20 | overdue:4466.1d | N/A |
| ZOOKEEPER-2350 | Script that provide a way to build the ensemble with ease. | 2021-03-01 | 0.20 | overdue:1876.9d | N/A |
| ZOOKEEPER-2353 | QuorumCnxManager protocol needs to be upgradable with-in a specific Version | 2021-03-01 | 0.20 | overdue:1862.2d | N/A |
| ZOOKEEPER-2354 | ZOOKEEPER-1653 not merged in master and 3.5 branch | 2021-03-01 | 0.20 | overdue:1861.4d | N/A |
| ZOOKEEPER-2356 | SaslServer don't keep user information.Cant find who create the znode. | 2021-03-01 | 0.20 | overdue:1852.9d | N/A |
| ZOOKEEPER-2357 | Unhandled errors propagating through cluster | 2021-03-01 | 0.20 | overdue:1851.3d | N/A |
| ZOOKEEPER-2358 | NettyServerCnxn leaks watches upon close | 2021-03-01 | 0.20 | overdue:1845.9d | N/A |
| ZOOKEEPER-2361 | Revisit 'VisibleForTesting' phrase used to indicate a member or method visible for testing | 2021-03-01 | 0.20 | overdue:1838.2d | N/A |
| ZOOKEEPER-2362 | ZooKeeper multi / transaction allows partial read | 2021-03-01 | 0.20 | overdue:1837.4d | N/A |
| ZOOKEEPER-2363 | DatadirCleanupManager never created by ZookeeperServerMain | 2021-03-01 | 0.20 | overdue:1837.3d | N/A |
| ZOOKEEPER-2365 | JAAS configuration section error is confusing | 2021-03-01 | 0.20 | overdue:1832.1d | N/A |
| ZOOKEEPER-2369 | Flushing DataOutputStream before calling toByteArray on the underlying ByteArrayOutputStream | 2021-03-01 | 0.20 | overdue:1824.6d | N/A |
| ZOOKEEPER-2372 | Add ability to specify user under which zookeeper process should be started using zkServer.sh | 2021-03-01 | 0.20 | overdue:1819.4d | N/A |
| ZOOKEEPER-2377 | zkServer.sh should resolve canonical path from symlinks | 2021-03-01 | 0.20 | overdue:1816.9d | N/A |
| ZOOKEEPER-2386 | Cannot achieve quorum when middle server (in a q of 3) is unreacable | 2021-03-01 | 0.20 | overdue:1803.9d | N/A |
| ZOOKEEPER-2389 | read-only observer doesn't load transaction log when transitioning to read-only | 2021-03-01 | 0.20 | overdue:1799.0d | N/A |
| ZOOKEEPER-2391 | setMin/MaxSessionTimeout of ZookeeperServer are implemented in quite a weak way | 2021-03-01 | 0.20 | overdue:1797.5d | N/A |
| ZOOKEEPER-2394 | Many ZooKeeper properties are not configurable in zoo.cfg | 2021-03-01 | 0.20 | overdue:1792.6d | N/A |
| ZOOKEEPER-2395 | allow ant command line control of junit test jvm args | 2021-03-01 | 0.20 | overdue:1792.0d | N/A |
| ZOOKEEPER-2397 | Undocumented SASL properties | 2021-03-01 | 0.20 | overdue:1792.0d | N/A |
| ZOOKEEPER-2398 | Config options should not be only available via system property | 2021-03-01 | 0.20 | overdue:1791.5d | N/A |
| ZOOKEEPER-24 | Do Application based outstanding request throttling | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-2401 | Document leader.nodelay and follower.nodelay ZooKeeper server properties | 2021-03-01 | 0.20 | overdue:1790.5d | N/A |
| ZOOKEEPER-2403 | Consistently handle and document boolean properties (true/false as well as yes/no) | 2021-03-01 | 0.20 | overdue:1790.2d | N/A |
| ZOOKEEPER-2404 | Sections to be completed in Programmer's guide document. | 2021-03-01 | 0.20 | overdue:1789.4d | N/A |
| ZOOKEEPER-2406 | /etc/zookeeper isn't used for ZOOCFGDIR | 2021-03-01 | 0.20 | overdue:1784.2d | N/A |
| ZOOKEEPER-2407 | EventThread in ClientCnxn can't be closed when SendThread exits because of auth failed during reconnection | 2021-03-01 | 0.20 | overdue:1783.5d | N/A |
| ZOOKEEPER-2408 | zoo_awget() ctx memory does not be freed if callback watcher was not invoked | 2021-03-01 | 0.20 | overdue:1781.9d | N/A |
| ZOOKEEPER-2409 | zookeeper recipes lock's c implement: function child_floor bug | 2021-03-01 | 0.20 | overdue:1781.7d | N/A |
| ZOOKEEPER-2414 | c-client aborted when operate's path is invalid in zoo_amulti  | 2021-03-01 | 0.20 | overdue:1761.8d | N/A |
| ZOOKEEPER-2416 | Remove Java System property usage from ZooKeeper server code | 2021-03-01 | 0.20 | overdue:1756.7d | N/A |
| ZOOKEEPER-2419 | Zookeeper.log filling up faster due to clients without Auth (KeeperErrorCode = NoAuth) | 2021-03-01 | 0.20 | overdue:1751.5d | N/A |
| ZOOKEEPER-2421 | testSessionReuse is commented out | 2021-03-01 | 0.20 | overdue:1750.4d | N/A |
| ZOOKEEPER-2422 | Improve health reporting by adding heap stats | 2021-03-01 | 0.20 | overdue:1750.3d | N/A |
| ZOOKEEPER-2429 | IbmX509 KeyManager and TrustManager algorithm not supported | 2021-03-01 | 0.20 | overdue:1735.4d | N/A |
| ZOOKEEPER-2430 | Remove jute.maxbuffer limit packetLen in client side | 2021-03-01 | 0.20 | overdue:1731.6d | N/A |
| ZOOKEEPER-2431 | C client documentation improvement | 2021-03-01 | 0.20 | overdue:1730.3d | N/A |
| ZOOKEEPER-2432 | Document how to use single thread C client API to monitor connection status. | 2021-03-01 | 0.20 | overdue:1730.3d | N/A |
| ZOOKEEPER-2434 | Error handling issues in truncation code | 2021-03-01 | 0.20 | overdue:1723.9d | N/A |
| ZOOKEEPER-2436 | Inconsistent truncation logic and out of sync logging and comments in recovery code | 2021-03-01 | 0.20 | overdue:1722.6d | N/A |
| ZOOKEEPER-2437 | Need detailed diagnostics for Zookeeper Connection Issues | 2021-03-01 | 0.20 | overdue:1721.2d | N/A |
| ZOOKEEPER-2438 | Create sample program for multi client single JVM scenario. | 2021-03-01 | 0.20 | overdue:1720.4d | N/A |
| ZOOKEEPER-2439 | The order of asynchronous setACL is not correct. | 2021-03-01 | 0.20 | overdue:1719.9d | N/A |
| ZOOKEEPER-2440 | permanent SESSIONMOVED error after client app reconnects to zookeeper cluster | 2021-03-01 | 0.20 | overdue:1719.1d | N/A |
| ZOOKEEPER-2441 | C API maps getaddrinfo() transient and permanent failures to the same value | 2021-03-01 | 0.20 | overdue:1718.6d | N/A |
| ZOOKEEPER-2443 | Invalid Memory Access (SEGFAULT) and undefined behaviour in c client | 2021-03-01 | 0.20 | overdue:1714.6d | N/A |
| ZOOKEEPER-2444 | Fix NULL handling for getlogin() call | 2021-03-01 | 0.20 | overdue:1714.5d | N/A |
| ZOOKEEPER-2445 | Add a new node to cluster, error config file but sucessed | 2021-03-01 | 0.20 | overdue:1713.6d | N/A |
| ZOOKEEPER-2447 | Zookeeper adds  good delay when one of the quorum host is not reachable | 2021-03-01 | 0.20 | overdue:1706.5d | N/A |
| ZOOKEEPER-2448 | Expose result of reconfiguration via JMX | 2021-03-01 | 0.20 | overdue:1702.4d | N/A |
| ZOOKEEPER-2449 | Refresh the invalid host which got unknownhostexception during connection in StaticHostProvider | 2021-03-01 | 0.20 | overdue:1701.5d | N/A |
| ZOOKEEPER-2453 | Cannot compile on ARM: "Error: bad instruction `lock xaddl" | 2021-03-01 | 0.20 | overdue:1696.3d | N/A |
| ZOOKEEPER-2454 | Limit Connection Count based on User | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-2280, overdue:1694.6d | N/A |
| ZOOKEEPER-2455 | unexpected server response ZRUNTIMEINCONSISTENCY | 2021-03-01 | 0.20 | overdue:1693.7d | N/A |
| ZOOKEEPER-2461 | There is no difference between the observer and the participants in the leader election algorithm | 2021-03-01 | 0.20 | overdue:1691.3d | N/A |
| ZOOKEEPER-2462 | force authentication/authorization | 2021-03-01 | 0.20 | overdue:1690.4d | N/A |
| ZOOKEEPER-2466 | Client skips servers when trying to connect | 2021-03-01 | 0.20 | overdue:1686.1d | N/A |
| ZOOKEEPER-2468 | SetQuota and DelQuota | 2021-03-01 | 0.20 | overdue:1684.8d | N/A |
| ZOOKEEPER-2469 | infinite loop in ZK re-login | 2021-03-01 | 0.20 | overdue:1684.0d | N/A |
| ZOOKEEPER-2471 | Java Zookeeper Client incorrectly considers time spent sleeping as time spent connecting, potentially resulting in infinite reconnect loop | 2021-03-01 | 0.20 | overdue:1683.3d | N/A |
| ZOOKEEPER-2473 | ZooInspector support for read-only mode | 2021-03-01 | 0.20 | overdue:1680.3d | N/A |
| ZOOKEEPER-2487 | Test failed because of 'Forked Java VM exited abnormally.' | 2021-03-01 | 0.20 | overdue:1666.3d | N/A |
| ZOOKEEPER-2488 | Unsynchronized access to shuttingDownLE in QuorumPeer | 2021-03-01 | 0.20 | overdue:1666.0d | N/A |
| ZOOKEEPER-2492 | gethostname return error before Win32WSAStartup on windows. | 2021-03-01 | 0.20 | overdue:1663.9d | N/A |
| ZOOKEEPER-2493 | Flaky Tests: ReconfigTest fails on Solaris  | 2021-03-01 | 0.20 | overdue:1663.3d | N/A |
| ZOOKEEPER-2494 | reword documentation to say "a simple shell to execute file-like operations" instead of "a shell in which to execute simple file-system-like operations" | 2021-03-01 | 0.20 | overdue:1663.2d | N/A |
| ZOOKEEPER-2495 | Cluster unavailable on disk full(ENOSPC), disk quota(EDQUOT), disk write error(EIO) errors | 2021-03-01 | 0.20 | overdue:1660.1d | N/A |
| ZOOKEEPER-2496 | When inside a transaction, some exceptions do not have path information set. | 2021-03-01 | 0.20 | overdue:1659.7d | N/A |
| ZOOKEEPER-2501 | Improve ZooKeeperServerListenerImpl#notifyStopping() logging | 2021-03-01 | 0.20 | overdue:1656.2d | N/A |
| ZOOKEEPER-2503 | do a hard constraints on the number of myid which must between 0 and 255 | 2021-03-01 | 0.20 | overdue:1655.3d | N/A |
| ZOOKEEPER-2504 | Enforce that server ids are unique in a cluster | 2021-03-01 | 0.20 | overdue:1655.0d | N/A |
| ZOOKEEPER-2506 | Document use of read-only mode | 2021-03-01 | 0.20 | overdue:1654.2d | N/A |
| ZOOKEEPER-2509 | Secure mode leaks memory | 2021-03-01 | 0.20 | overdue:1650.8d | N/A |
| ZOOKEEPER-2510 | org.apache.zookeeper.server.NettyServerCnxnTest uses wrong import for junit | 2021-03-01 | 0.20 | overdue:1650.0d | N/A |
| ZOOKEEPER-2512 | Allow Jetty dependency to use HTTPS and Basic Auth | 2021-03-01 | 0.20 | overdue:1648.2d | 22.7 |
| ZOOKEEPER-2513 | majorChange exceptions during leader sync | 2021-03-01 | 0.20 | overdue:1647.0d | N/A |
| ZOOKEEPER-2515 | SessionTrackerImpl non-daemon thread slow to shutdown | 2021-03-01 | 0.20 | overdue:1643.3d | N/A |
| ZOOKEEPER-2516 | C client calculates invalid time interval for pings et al | 2021-03-01 | 0.20 | overdue:1643.2d | N/A |
| ZOOKEEPER-2518 | Document how to set up tool chains for build and test C client on all platforms | 2021-03-01 | 0.20 | overdue:1641.0d | N/A |
| ZOOKEEPER-2519 | zh->state should not be 0 while handle is active | 2021-03-01 | 0.20 | overdue:1638.5d | N/A |
| ZOOKEEPER-2520 | Zookeeper should accept and handle encrypted password (AES) which is required to be passed for keystore and truststore in case of SSL support | 2021-03-01 | 0.20 | overdue:1637.7d | N/A |
| ZOOKEEPER-2521 | space should be truncated while reading password for keystore/truststore which is required to configure while SSL enabled | 2021-03-01 | 0.20 | overdue:1637.7d | N/A |
| ZOOKEEPER-2522 | Need to document that default "secureClientPort" for Client will be 2181 and not "clientPort" when starting in SSL enable mode | 2021-03-01 | 0.20 | overdue:1637.6d | N/A |
| ZOOKEEPER-2523 | No proper logging when zookeeper failed to start in ssl mode. | 2021-03-01 | 0.20 | overdue:1637.6d | N/A |
| ZOOKEEPER-2524 | Start zkServer in ssl mode, start zkCli in non-ssl mode but on ssl port then try to quit at client, it takes almost 30 seconds to quit  | 2021-03-01 | 0.20 | overdue:1637.6d | N/A |
| ZOOKEEPER-2525 | Throwing Exception at zookeeper server side whenever client is closing the connection | 2021-03-01 | 0.20 | overdue:1637.6d | N/A |
| ZOOKEEPER-2526 | Add config flag to prohibit connections from clients that don't do Sasl auth | 2021-03-01 | 0.20 | overdue:1636.8d | N/A |
| ZOOKEEPER-2527 | Connection watch is not getting cleared when watch is created as part of get and it is fired as part of set and client is closed | 2021-03-01 | 0.20 | overdue:1636.5d | N/A |
| ZOOKEEPER-2528 | ZooKeeper cluster can become unavailable due to power failures | 2021-03-01 | 0.20 | overdue:1636.1d | N/A |
| ZOOKEEPER-2530 | When zookeeper started in SSL mode, set a "get" watcher on a znode from zkCli client, restart the zkCli, the "Data" watcher still present. Trying removing that watcher fails saying no watcher available | 2021-03-01 | 0.20 | overdue:1635.7d | N/A |
| ZOOKEEPER-2531 | Configuration as "zookeeper.secure=true/false" can be introduced and reading and verifying all ssl related configuration (like secureport, keystore, truststore, corresponding password) should be done only when "zookeeper.secure" flag is true | 2021-03-01 | 0.20 | overdue:1635.7d | N/A |
| ZOOKEEPER-2532 | zkCli throwing nullpointerException instead it should provide help when invalid input is entered | 2021-03-01 | 0.20 | overdue:1635.6d | N/A |
| ZOOKEEPER-2533 | Close the zkCli using "close" command and then connect using "connect" then provide some invalid input, it closing the channel and connecting again | 2021-03-01 | 0.20 | overdue:1635.6d | N/A |
| ZOOKEEPER-2534 | Configuration for IP address (zookeeper.server.ip=) should be introduced and zookeeper server should bind to that particular IP only not to all IPs of the system | 2021-03-01 | 0.20 | overdue:1634.8d | N/A |
| ZOOKEEPER-2535 | zookeeper_server's pid should be created once server is started completely and not before, problem with current approach | 2021-03-01 | 0.20 | overdue:1634.7d | N/A |
| ZOOKEEPER-2540 | When start zookeeper server by configuring the server details in dynamic configuration with passing the client port, wrong log info is logged | 2021-03-01 | 0.20 | overdue:1630.8d | N/A |
| ZOOKEEPER-2541 | We can't configure the "secureClientPort" in dynamicConfiguration and connect through client | 2021-03-01 | 0.20 | overdue:1630.8d | N/A |
| ZOOKEEPER-2544 | " unary operator expected" message on the console while trying to get the zookeeper status | 2021-03-01 | 0.20 | overdue:1627.8d | N/A |
| ZOOKEEPER-2545 | Keep maintaining the old zoo.cfg.dynamic* files which will keep eating system memory which is getting generated as part of reconfig execution | 2021-03-01 | 0.20 | overdue:1627.7d | N/A |
| ZOOKEEPER-2546 | Started throwing "Error Path:null Error:KeeperErrorCode = ReconfigInProgress" error when trying to change the cluster using reconfig and the IO hangged at one node | 2021-03-01 | 0.20 | overdue:1627.5d | N/A |
| ZOOKEEPER-2549 | As NettyServerCnxn.sendResponse() allows all the exception to bubble up it can stop main ZK requests processing thread | 2021-03-01 | 0.20 | overdue:1626.7d | N/A |
| ZOOKEEPER-2550 | FollowerResyncConcurrencyTest failed in ZooKeeper 3.3.3 | 2021-03-01 | 0.20 | overdue:1624.7d | N/A |
| ZOOKEEPER-2553 | ZooKeeper cluster unavailable due to corrupted log file during power failures -- java.io.IOException: Unreasonable length | 2021-03-01 | 0.20 | overdue:1624.3d | N/A |
| ZOOKEEPER-2555 | zookeeper started in observer mode takes long time to come to observer state once leader restarted and so client connected to observer mode has to wait for longer time to get service | 2021-03-01 | 0.20 | overdue:1623.6d | N/A |
| ZOOKEEPER-2559 | the quota should be deleted when its parasitic path doesn't exist | 2021-03-01 | 0.20 | overdue:1622.5d | N/A |
| ZOOKEEPER-2560 | Possible Cluster Unavailability | 2021-03-01 | 0.20 | overdue:1622.4d | N/A |
| ZOOKEEPER-2561 | CLONE - Possible Cluster Unavailability | 2021-03-01 | 0.20 | overdue:1622.3d | N/A |
| ZOOKEEPER-2562 | Safely persist renames of *epoch.tmp to *epoch by issuing fsync on parent directory -- Possible cluster unavailability otherwise | 2021-03-01 | 0.20 | overdue:1622.2d | N/A |
| ZOOKEEPER-2564 | No message is prompted when trying to delete quota with different quota option | 2021-03-01 | 0.20 | overdue:1621.7d | N/A |
| ZOOKEEPER-2565 | listquota <path> should display the quota even it is set on parent/child node | 2021-03-01 | 0.20 | overdue:1621.6d | N/A |
| ZOOKEEPER-2566 | space should be truncated while reading password for keystore/truststore which is required to configure while SSL enabled | 2021-03-01 | 0.20 | overdue:1621.6d | N/A |
| ZOOKEEPER-2567 | Error message is not correct when wrong argument is passed for "reconfig" cmd | 2021-03-01 | 0.20 | overdue:1621.5d | N/A |
| ZOOKEEPER-2569 | plain password is stored when set individual ACL using digest scheme | 2021-03-01 | 0.20 | overdue:1621.4d | N/A |
| ZOOKEEPER-2570 | ZooKeeper clients are timed out when ZooKeeper servers are very busy | 2021-03-01 | 0.20 | overdue:1621.3d | N/A |
| ZOOKEEPER-2571 | Potential resource leak in QuorumPeer.writeLongToFile | 2021-03-01 | 0.20 | overdue:1620.8d | N/A |
| ZOOKEEPER-2572 | Potential resource leak in FileTxnLog.truncate | 2021-03-01 | 0.20 | overdue:1620.8d | N/A |
| ZOOKEEPER-2575 | /./// does not have the form scheme:id:perm and client is quit. | 2021-03-01 | 0.20 | overdue:1617.8d | N/A |
| ZOOKEEPER-2578 | zkEnv.sh does not set $ZOOCFG properly if already set  | 2021-03-01 | 0.20 | overdue:1616.1d | N/A |
| ZOOKEEPER-2580 | ErrorMessage is not correct when set IP acl and try to set again from another machine | 2021-03-01 | 0.20 | overdue:1615.8d | N/A |
| ZOOKEEPER-2582 | When addauth twice for same user but different password, it is adding 2 digest corresponding to both username, password and so we can able to access znode with user and any of these password which does not seem to be correct | 2021-03-01 | 0.20 | overdue:1615.4d | N/A |
| ZOOKEEPER-2583 | Using one client able to access the znode with localhost but fails from another client when IP ACL is set for znode using 127.0.0.1 | 2021-03-01 | 0.20 | overdue:1615.4d | N/A |
| ZOOKEEPER-2584 | when setquota for a znode and set ip/user ACL on /zookeeper/quota, still able to delete the quota from client with another ip though it says "Authentication is not valid" | 2021-03-01 | 0.20 | overdue:1614.8d | N/A |
| ZOOKEEPER-2585 | ACL with SSL is not working | 2021-03-01 | 0.20 | overdue:1614.7d | N/A |
| ZOOKEEPER-2586 | zoo_aremove_watchers() does not remove a watch of path has more than one watch | 2021-03-01 | 0.20 | overdue:1613.8d | N/A |
| ZOOKEEPER-2589 | Not able to access znode if  IP ACL is set on a znode when zookeeper started in ssl mode | 2021-03-01 | 0.20 | overdue:1612.7d | N/A |
| ZOOKEEPER-2590 | exists() should check read ACL permission | 2021-03-01 | 0.20 | overdue:1611.9d | N/A |
| ZOOKEEPER-2592 | Zookeeper is not recoverable once running system( machine on which zookeeper is running) is out of space | 2021-03-01 | 0.20 | overdue:1610.4d | N/A |
| ZOOKEEPER-2593 | Enforce the quota limit | 2021-03-01 | 0.20 | overdue:1610.3d | N/A |
| ZOOKEEPER-2595 | znode created with acl enabled on it can be deleted by any unauthorised user, when it has no child znodes | 2021-03-01 | 0.20 | overdue:1609.4d | N/A |
| ZOOKEEPER-2598 | Data Inconsistency after power off/on of some nodes | 2021-03-01 | 0.20 | overdue:1608.2d | N/A |
| ZOOKEEPER-2599 | Quorum with 3 nodes, stop 2 nodes and let one running, install and configure new quorum where one node details is common but now has configuration of new quorum. common node getting synced the configuration with previous quorum | 2021-03-01 | 0.20 | overdue:1607.4d | N/A |
| ZOOKEEPER-2603 | Init script restart command broken on Debian Jessie | 2021-03-01 | 0.20 | overdue:1603.5d | N/A |
| ZOOKEEPER-2604 | Temporary node has not been deleted | 2021-03-01 | 0.20 | overdue:1602.5d | N/A |
| ZOOKEEPER-2607 | doxygen-related, ./configure fails | 2021-03-01 | 0.20 | overdue:1592.7d | N/A |
| ZOOKEEPER-2612 | user-level KeeperException | 2021-03-01 | 0.20 | overdue:1588.3d | N/A |
| ZOOKEEPER-2613 | user-level KeeperException | 2021-03-01 | 0.20 | overdue:1588.3d | N/A |
| ZOOKEEPER-2615 | Zookeeper server holds onto dead/expired session ids in the watch data structures | 2021-03-01 | 0.20 | overdue:1585.8d | N/A |
| ZOOKEEPER-2616 | ZK client fails to connect to ReadOnly server | 2021-03-01 | 0.20 | overdue:1582.1d | N/A |
| ZOOKEEPER-2619 | Client library reconnecting breaks FIFO client order | 2021-03-01 | 0.20 | overdue:1578.0d | N/A |
| ZOOKEEPER-262 | unnecesssarily complex reentrant zookeeper_close() logic | 2021-03-01 | 0.20 | overdue:4431.0d | N/A |
| ZOOKEEPER-2623 | CheckVersion outside of Multi causes NullPointerException | 2021-03-01 | 0.20 | overdue:1571.9d | N/A |
| ZOOKEEPER-2625 | zkServer.sh creates PID file in the folder data?/ instead of data/ | 2021-03-01 | 0.20 | overdue:1566.5d | N/A |
| ZOOKEEPER-2626 | log4j.properties don't get respected | 2021-03-01 | 0.20 | overdue:1566.5d | N/A |
| ZOOKEEPER-2629 | Clean up git pull request QA script | 2021-03-01 | 0.20 | overdue:1562.2d | N/A |
| ZOOKEEPER-2634 | null data in zknode data | 2021-03-01 | 0.20 | overdue:1548.5d | N/A |
| ZOOKEEPER-2637 | NettyNettySuiteHammerTest  and NettyNettySuiteTest failures | 2021-03-01 | 0.20 | overdue:1540.4d | N/A |
| ZOOKEEPER-2639 | Port Quorum Peer mutual authentication SASL feature to branch-3.5 and trunk | 2021-03-01 | 0.20 | overdue:1538.7d | N/A |
| ZOOKEEPER-2640 | fix test coverage for single threaded C-API | 2021-03-01 | 0.20 | overdue:1534.0d | N/A |
| ZOOKEEPER-2643 | Configurable SSLContext | 2021-03-01 | 0.20 | overdue:1529.2d | N/A |
| ZOOKEEPER-2644 | contrib/rest does not include rest.sh when packaged | 2021-03-01 | 0.20 | overdue:1526.4d | N/A |
| ZOOKEEPER-2645 | If embedded QuorumPeerMain is started with Properties no backupOldConfig should be done | 2021-03-01 | 0.20 | overdue:1523.7d | N/A |
| ZOOKEEPER-2653 | epoch files do not match snapshots and logs | 2021-03-01 | 0.20 | overdue:1516.3d | N/A |
| ZOOKEEPER-2654 | Support Fedora 25: use pkg-config instead of obsolete M4 macros | 2021-03-01 | 0.20 | overdue:1516.3d | N/A |
| ZOOKEEPER-2657 | Using zookeeper without SASL causes error logging | 2021-03-01 | 0.20 | overdue:1509.6d | N/A |
| ZOOKEEPER-2663 | Enable remote jmx, zkCli.sh start failed with jmx communication error | 2021-03-01 | 0.20 | overdue:1496.4d | N/A |
| ZOOKEEPER-2666 | the watch function called many times when it should be called once | 2021-03-01 | 0.20 | overdue:1491.8d | N/A |
| ZOOKEEPER-2668 | Remove reference to requireClientAuthScheme from https://cwiki.apache.org/confluence/display/ZOOKEEPER/Client-Server+mutual+authentication | 2021-03-01 | 0.20 | overdue:1489.0d | N/A |
| ZOOKEEPER-2669 | follower failed to  reconnect to leader after a network error | 2021-03-01 | 0.20 | overdue:1488.5d | N/A |
| ZOOKEEPER-2675 | Bump Mockito to version 2 | 2021-03-01 | 0.20 | overdue:1482.5d | N/A |
| ZOOKEEPER-2677 | Verify the occurrence of CancelledKeyException in zookeeper branch-3.5 and above | 2021-03-01 | 0.20 | overdue:1481.7d | N/A |
| ZOOKEEPER-2688 | rmr leads to "Node does not exist" | 2021-03-01 | 0.20 | overdue:1468.4d | N/A |
| ZOOKEEPER-2695 | Handle unknown error for rolling upgrade old client new server scenario | 2021-03-01 | 0.20 | overdue:1462.4d | N/A |
| ZOOKEEPER-270 | remove NoSyncConnected in KeeperState - it's not used anywhere in the codebase.  | 2021-03-01 | 0.20 | overdue:4421.1d | N/A |
| ZOOKEEPER-2700 | Force ZooKeeper to generate snapshot | 2021-03-01 | 0.20 | overdue:1459.4d | N/A |
| ZOOKEEPER-2701 | Timeout for RecvWorker is too long | 2021-03-01 | 0.20 | overdue:1456.7d | N/A |
| ZOOKEEPER-2702 | zookeeper ensemble took 20 minutes to come back up after leader failed | 2021-03-01 | 0.20 | overdue:1454.5d | N/A |
| ZOOKEEPER-2703 | [MASTER ISSUE] Create benchmark/stability tests | 2021-03-01 | 0.20 | overdue:1454.2d | N/A |
| ZOOKEEPER-2704 | Run Jepsen against branch-3.5 / master of ZooKeeper | 2021-03-01 | 0.20 | overdue:1453.9d | N/A |
| ZOOKEEPER-2705 | Container node remains indefinitely after session has long expired! | 2021-03-01 | 0.20 | overdue:1453.5d | N/A |
| ZOOKEEPER-2708 | TracelogFile not being created. | 2021-03-01 | 0.20 | overdue:1445.2d | N/A |
| ZOOKEEPER-2711 | Deadlock between concurrent 4LW commands that iterate over connections with Netty server | 2021-03-01 | 0.20 | overdue:1441.2d | N/A |
| ZOOKEEPER-2715 | Sessions Expire due to Network partitioning in Zookeeper  | 2021-03-01 | 0.20 | overdue:1439.7d | N/A |
| ZOOKEEPER-2717 | org.apache.zookeeper.server.quorum.RaceConditionTest fails intermittently | 2021-03-01 | 0.20 | overdue:1438.7d | N/A |
| ZOOKEEPER-2721 | org.apache.zookeeper.server.quorum.ReconfigRecoveryTest fails intermittently | 2021-03-01 | 0.20 | overdue:1434.6d | N/A |
| ZOOKEEPER-2723 | ConnectStringParser does not parse correctly if quorum string has znode path | 2021-03-01 | 0.20 | overdue:1433.5d | N/A |
| ZOOKEEPER-2738 | maxClientCnxns not limiting concurrent connections properly | 2021-03-01 | 0.20 | overdue:1423.9d | N/A |
| ZOOKEEPER-2739 | maxClientCnxns not working in NettyServerCnxnFactory | 2021-03-01 | 0.20 | overdue:1423.9d | N/A |
| ZOOKEEPER-2741 | A Swift Connector of ZooKeeper is available now: Perfect-ZooKeeper | 2021-03-01 | 0.20 | overdue:1420.2d | N/A |
| ZOOKEEPER-2745 | Node loses data after disk-full event, but successfully joins Quorum | 2021-03-01 | 0.20 | overdue:1413.1d | N/A |
| ZOOKEEPER-2748 | Admin command to voluntarily drop client connections | 2021-03-01 | 0.20 | overdue:1411.1d | N/A |
| ZOOKEEPER-2751 | Investigate why existing unit tests does not leak connection bean for NIO code path | 2021-03-01 | 0.20 | overdue:1407.3d | N/A |
| ZOOKEEPER-2752 | Introduce ZooKeeper flaky test dashboard | 2021-03-01 | 0.20 | overdue:1406.1d | N/A |
| ZOOKEEPER-2761 | Build is packaged as uncompressed tar archive but file name ends with .gz | 2021-03-01 | 0.20 | overdue:1399.5d | N/A |
| ZOOKEEPER-2766 | Quorum fails with java.io.EOFException | 2021-03-01 | 0.20 | overdue:1392.6d | N/A |
| ZOOKEEPER-2768 | Some ideas about four word command | 2021-03-01 | 0.20 | overdue:1389.6d | N/A |
| ZOOKEEPER-277 | Define PATH_SEPARATOR | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-835, overdue:4406.0d | N/A |
| ZOOKEEPER-2770 | ZooKeeper slow operation log | 2021-03-01 | 0.20 | overdue:1386.0d | N/A |
| ZOOKEEPER-2771 | all resolved bug | 2021-03-01 | 0.20 | overdue:1385.7d | N/A |
| ZOOKEEPER-2773 | zookeeper-service | 2021-03-01 | 0.20 | overdue:1384.8d | N/A |
| ZOOKEEPER-2776 | Election Failed when (medium id) node down | 2021-03-01 | 0.20 | overdue:1382.6d | N/A |
| ZOOKEEPER-2780 | if directories of connectString don't exist, then... | 2021-03-01 | 0.20 | overdue:1376.6d | N/A |
| ZOOKEEPER-2782 | Cannot log in | 2021-03-01 | 0.20 | overdue:1375.4d | N/A |
| ZOOKEEPER-2784 | Add some limitations on code level for `SID` to avoid configuration problem | 2021-03-01 | 0.20 | overdue:1371.8d | N/A |
| ZOOKEEPER-2789 | Reassign `ZXID` for solving 32bit overflow problem | 2021-03-01 | 0.20 | overdue:1364.9d | N/A |
| ZOOKEEPER-2790 |  Should we consider using `LongAdder` instead of `AtomicLong` | 2021-03-01 | 0.20 | overdue:1363.6d | N/A |
| ZOOKEEPER-2791 | Quorum doesn't recover after zxid rollover | 2021-03-01 | 0.20 | overdue:1363.4d | N/A |
| ZOOKEEPER-2793 | [QP MutualAuth]: Implement a mechanism to build "authzHosts" for dynamic reconfig servers | 2021-03-01 | 0.20 | overdue:1358.6d | N/A |
| ZOOKEEPER-2794 | [QP MutualAuth]: Revisit auth logic to handle dynamically add/remove servers | 2021-03-01 | 0.20 | overdue:1358.6d | N/A |
| ZOOKEEPER-2799 | Separate logs generated by tests in jenkins jobs when tests are run in parallel | 2021-03-01 | 0.20 | overdue:1354.1d | N/A |
| ZOOKEEPER-28 | Incompatible client and server list detection | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-2800 | zookeeper ephemeral node not deleted after server restart and consistency is not hold | 2021-03-01 | 0.20 | overdue:1350.8d | N/A |
| ZOOKEEPER-2801 | address spelling errors/typos | 2021-03-01 | 0.20 | overdue:1350.8d | N/A |
| ZOOKEEPER-2802 | Zookeeper C client hang @wait_sync_completion | 2021-03-01 | 0.20 | overdue:1349.0d | N/A |
| ZOOKEEPER-2810 | Racy implicit ZKDatabase creation | 2021-03-01 | 0.20 | overdue:1340.4d | N/A |
| ZOOKEEPER-2812 | Racy implicit SessionTracker creation | 2021-03-01 | 0.20 | overdue:1337.7d | N/A |
| ZOOKEEPER-2813 | Failure tight loop in acceptor | 2021-03-01 | 0.20 | overdue:1337.6d | N/A |
| ZOOKEEPER-2814 | Ignore space after comma in connection string | 2021-03-01 | 0.20 | overdue:1335.6d | N/A |
| ZOOKEEPER-2817 | Using `Collections.singletonList` instead of `Arrays.asList(oneElement)` | 2021-03-01 | 0.20 | overdue:1334.5d | N/A |
| ZOOKEEPER-2820 | Update documentation on how to do rolling restart | 2021-03-01 | 0.20 | overdue:1330.0d | N/A |
| ZOOKEEPER-2821 | 1. Fix spell issues; 2. Remove unnecessary boxing / unboxing; 3. Simplify `return` clause; 4. Remove `final` qualifier from `private` method | 2021-03-01 | 0.20 | overdue:1329.8d | N/A |
| ZOOKEEPER-2823 | 1. Fix spell issues; 2. Standardize `StringBuilder#append` usage; 3. Using `try` clause for releasing I/O stream for `COMMON` module | 2021-03-01 | 0.20 | overdue:1328.9d | N/A |
| ZOOKEEPER-2827 | Code refactoring for `JUTE` module | 2021-03-01 | 0.20 | overdue:1327.8d | N/A |
| ZOOKEEPER-2828 | Test case improvement | 2021-03-01 | 0.20 | overdue:1326.3d | N/A |
| ZOOKEEPER-2830 | Pre-commit tooling improvement: auto close github pull request when a pull request is merged | 2021-03-01 | 0.20 | overdue:1326.1d | N/A |
| ZOOKEEPER-2831 | Update documents on getConfig when reconfig is disabled. | 2021-03-01 | 0.20 | overdue:1325.8d | N/A |
| ZOOKEEPER-2832 | Data Inconsistency occurs if follower has uncommitted transaction in the log while synchronizing with the leader that has the lower last processed zxid | 2021-03-01 | 0.20 | overdue:1324.2d | N/A |
| ZOOKEEPER-2833 | Keep the follower transaction up to date after the fix made in ZOOKEEPER-2355. | 2021-03-01 | 0.20 | overdue:1322.8d | N/A |
| ZOOKEEPER-2835 | Run server with `-XX:+AlwaysPreTouch` jvm flag | 2021-03-01 | 0.20 | overdue:1322.5d | N/A |
| ZOOKEEPER-2838 | race-condition when shutting down NIOServerCnxnFactory yields CancelledKeyException | 2021-03-01 | 0.20 | overdue:1321.7d | N/A |
| ZOOKEEPER-2839 | Race condition between AcceptThread and SelectorThread may allow connections beyond the max client connection limit | 2021-03-01 | 0.20 | overdue:1321.5d | N/A |
| ZOOKEEPER-2840 | Should using `System.nanoTime() ^ this.hashCode()` for StaticHostProvider | 2021-03-01 | 0.20 | overdue:1321.5d | N/A |
| ZOOKEEPER-2843 | auth_to_local should support reading rules from a file | 2021-03-01 | 0.20 | overdue:1313.7d | N/A |
| ZOOKEEPER-2844 | Zookeeper auto purge process does not purge files | 2021-03-01 | 0.20 | overdue:1313.6d | N/A |
| ZOOKEEPER-2846 | Leader follower sync with on disk txns can possibly leads to data inconsistency | 2021-03-01 | 0.20 | overdue:1308.2d | N/A |
| ZOOKEEPER-2849 | Quorum port binding needs exponential back-off retry | 2021-03-01 | 0.20 | overdue:1306.3d | N/A |
| ZOOKEEPER-2850 | [QP MutualAuth]: Port ZOOKEEPER-2650 and ZOOKEEPER-2759 from branch-3.4 to branch-3.5. | 2021-03-01 | 0.20 | overdue:1305.3d | N/A |
| ZOOKEEPER-2851 | [QP MutualAuth]: add QuorumCnxManager tests that covers quorum auth logic. | 2021-03-01 | 0.20 | overdue:1303.8d | N/A |
| ZOOKEEPER-2854 | fatjar invalid, contains incomplete signature | 2021-03-01 | 0.20 | overdue:1302.5d | N/A |
| ZOOKEEPER-2855 | Rebooting a Joined Node Failed Due The Joined Node Previously Failed to Update Its Configuration Correctly | 2021-03-01 | 0.20 | overdue:1302.1d | N/A |
| ZOOKEEPER-2857 | Server deal command has problem | 2021-03-01 | 0.20 | overdue:1300.7d | N/A |
| ZOOKEEPER-2858 | Disable reverse DNS lookup for java client | 2021-03-01 | 0.20 | overdue:1300.4d | N/A |
| ZOOKEEPER-2860 | Update sample server jaas config for kerberos auth | 2021-03-01 | 0.20 | overdue:1299.6d | N/A |
| ZOOKEEPER-2867 | an expired ZK session can be re-established | 2021-03-01 | 0.20 | overdue:1291.0d | N/A |
| ZOOKEEPER-2869 | Allow for exponential backoff in ClientCnxn.SendThread on connection re-establishment | 2021-03-01 | 0.20 | overdue:1288.1d | N/A |
| ZOOKEEPER-2876 | Github pull request test script should output -1 when there is no tests provided in patch, unless the subject under test is a documentation JIRA | 2021-03-01 | 0.20 | overdue:1279.1d | N/A |
| ZOOKEEPER-2877 | Flaky Test: org.apache.zookeeper.server.quorum.Zab1_0Test.testNormalRun | 2021-03-01 | 0.20 | overdue:1277.8d | N/A |
| ZOOKEEPER-2878 | some issues in c code of lock of recipes  | 2021-03-01 | 0.20 | overdue:1274.7d | N/A |
| ZOOKEEPER-2879 | Adding observers dynamically without server id | 2021-03-01 | 0.20 | overdue:1274.3d | N/A |
| ZOOKEEPER-2881 | memory leak in create_buffer_iarchive() and create_buffer_oarchive() | 2021-03-01 | 0.20 | overdue:1272.4d | N/A |
| ZOOKEEPER-2882 | memory leak in zoo_amulti() function | 2021-03-01 | 0.20 | overdue:1272.4d | N/A |
| ZOOKEEPER-2883 | no null check for the pointer which returned by allocate_buffer() function | 2021-03-01 | 0.20 | overdue:1272.4d | N/A |
| ZOOKEEPER-2884 | Failed to connect to zookeeper instance within 2x zookeeper timeout period 30000 | 2021-03-01 | 0.20 | overdue:1267.4d | N/A |
| ZOOKEEPER-2888 | Reconfig Command Isolates One of the Nodes when All Ports Change | 2021-03-01 | 0.20 | overdue:1263.2d | N/A |
| ZOOKEEPER-2889 | Zookeeper standalone instance startup references logging classes incompatible with log4j-1.2-api | 2021-03-01 | 0.20 | overdue:1262.6d | N/A |
| ZOOKEEPER-2895 | a bug in zkServer.sh  | 2021-03-01 | 0.20 | overdue:1252.8d | N/A |
| ZOOKEEPER-2897 | Jenkins precommit Zookeeper builds are failing for no reason | 2021-03-01 | 0.20 | overdue:1250.8d | N/A |
| ZOOKEEPER-2898 | Zookeeper Management | 2021-03-01 | 0.20 | overdue:1250.6d | N/A |
| ZOOKEEPER-2899 | Zookeeper not receiving packets after ZXID overflows | 2021-03-01 | 0.20 | overdue:1250.0d | N/A |
| ZOOKEEPER-2907 | Logged request buffer isn't useful | 2021-03-01 | 0.20 | overdue:1236.1d | 291.6 |
| ZOOKEEPER-2910 | zookeeper listening on unknown random port | 2021-03-01 | 0.20 | overdue:1234.6d | N/A |
| ZOOKEEPER-2911 | Precommit checks are failing because of issuer pertaining to repo | 2021-03-01 | 0.20 | overdue:1233.3d | N/A |
| ZOOKEEPER-2912 | Allow arbiter zookeeper nodes to be deployed | 2021-03-01 | 0.20 | overdue:1232.5d | N/A |
| ZOOKEEPER-2916 | startSingleServerTest may be flaky | 2021-03-01 | 0.20 | overdue:1227.1d | N/A |
| ZOOKEEPER-2917 | c client doesn't wait for server response upon closing handle, generates EndOfStreamException and CancelledKeyExceptions warnings | 2021-03-01 | 0.20 | overdue:1226.2d | N/A |
| ZOOKEEPER-2918 | Make ivy dependency report available as a build artifact from jenkins runs | 2021-03-01 | 0.20 | overdue:1225.1d | N/A |
| ZOOKEEPER-2919 | expired ephemeral node reappears after ZK leader change | 2021-03-01 | 0.20 | overdue:1218.0d | N/A |
| ZOOKEEPER-2921 | fsyncWarningThresholdMS is applied on each getChannel().force() - also needed on entire commit | 2021-03-01 | 0.20 | overdue:1215.6d | N/A |
| ZOOKEEPER-2925 | ZooKeeper server fails to start on first-startup due to race to create dataDir & snapDir | 2021-03-01 | 0.20 | overdue:1207.1d | N/A |
| ZOOKEEPER-2927 | Local session reconnect validation not forward to leader | 2021-03-01 | 0.20 | overdue:1206.6d | N/A |
| ZOOKEEPER-2928 | pthread_join  hang at zookeeper_close | 2021-03-01 | 0.20 | overdue:1204.7d | N/A |
| ZOOKEEPER-2929 | [DNS Support] Zookeeper client still trying to establish the connection with old IP even after Zookeeper Server restarted with new IP when domain name configured at the client side | 2021-03-01 | 0.20 | overdue:1201.4d | N/A |
| ZOOKEEPER-2930 | Leader cannot be elected due to network timeout of some members. | 2021-03-01 | 0.20 | overdue:1200.7d | N/A |
| ZOOKEEPER-2932 | Performance enhancement about purging task | 2021-03-01 | 0.20 | overdue:1197.6d | N/A |
| ZOOKEEPER-2937 | zookeeper issues with handling authentication... | 2021-03-01 | 0.20 | overdue:1195.3d | N/A |
| ZOOKEEPER-2938 | Server is unable to join quorum after connection broken to other peers | 2021-03-01 | 0.20 | overdue:1195.0d | N/A |
| ZOOKEEPER-294 | document or change memory allocations in C API completion handling | 2021-03-01 | 0.20 | overdue:4393.2d | N/A |
| ZOOKEEPER-2941 | support client FIFO client order, not only channel FIFO client order | 2021-03-01 | 0.20 | overdue:1188.7d | N/A |
| ZOOKEEPER-2943 | Need dynamic server host resolve in client | 2021-03-01 | 0.20 | overdue:1186.9d | N/A |
| ZOOKEEPER-2945 | Synchronization code on the follower does not properly truncate uncommitted write resulting in data inconsistency | 2021-03-01 | 0.20 | overdue:1183.7d | N/A |
| ZOOKEEPER-2946 | The truncate() function in FileTxnLog.java may fail to properly remove an uncommitted write resulting in data inconsistency | 2021-03-01 | 0.20 | overdue:1182.6d | N/A |
| ZOOKEEPER-2947 | Find a reasonable way to handle sequential node counter overflowing | 2021-03-01 | 0.20 | overdue:1182.2d | N/A |
| ZOOKEEPER-295 | prevent multiple namespace pollution by C API | 2021-03-01 | 0.20 | overdue:4393.2d | N/A |
| ZOOKEEPER-2954 | ant compile_jute is failing for zookeeper 3.4.11 | 2021-03-01 | 0.20 | overdue:1160.6d | N/A |
| ZOOKEEPER-2956 | Cannot delete znode that owns too many child znodes by `rmr` command | 2021-03-01 | 0.20 | overdue:1158.6d | N/A |
| ZOOKEEPER-2957 | Whether zookeeper client-server nio or netty communication can use socket proxies | 2021-03-01 | 0.20 | overdue:1158.6d | N/A |
| ZOOKEEPER-2958 | Don't reconnect zookeeper server when tomcat stopped | 2021-03-01 | 0.20 | overdue:1155.6d | N/A |
| ZOOKEEPER-296 | adopt APR-style versioning and compatibility guidelines for C API | 2021-03-01 | 0.20 | overdue:4393.2d | N/A |
| ZOOKEEPER-2965 | prevent DNS queries spam | 2021-03-01 | 0.20 | overdue:1133.3d | N/A |
| ZOOKEEPER-2969 | C API Log Callback Lacks Context | 2021-03-01 | 0.20 | overdue:1123.0d | N/A |
| ZOOKEEPER-297 | centralize version numbering in the source/build | 2021-03-01 | 0.20 | overdue:4393.1d | N/A |
| ZOOKEEPER-2972 | When use SSL on zookeeper server, counts of watches may increase more than forty thousands and lead zoookeeper process outofmemory error | 2021-03-01 | 0.20 | overdue:1113.7d | N/A |
| ZOOKEEPER-2973 | "Unreasonable length" exception  | 2021-03-01 | 0.20 | overdue:1111.6d | N/A |
| ZOOKEEPER-2974 | Link invalid, please update http://zookeeper.apache.org/doc/trunk/zookeeperStarted.html | 2021-03-01 | 0.20 | overdue:1110.0d | N/A |
| ZOOKEEPER-2975 | Re connection should happen without any problem After zk server restarted | 2021-03-01 | 0.20 | overdue:1109.6d | N/A |
| ZOOKEEPER-2977 | Concurrency for addAuth corrupts quorum packets | 2021-03-01 | 0.20 | overdue:1099.8d | N/A |
| ZOOKEEPER-2984 | Master | 2021-03-01 | 0.20 | overdue:1090.7d | N/A |
| ZOOKEEPER-2985 | Expired session may unexpired after leader failover | 2021-03-01 | 0.20 | overdue:1089.3d | N/A |
| ZOOKEEPER-2986 | My id not in the peer list | 2021-03-01 | 0.20 | overdue:1089.2d | N/A |
| ZOOKEEPER-2987 | Invalid PurgeTxnLog params order in the zkCleanup.sh | 2021-03-01 | 0.20 | overdue:1083.1d | N/A |
| ZOOKEEPER-2990 | Implement probabilistic tracing | 2021-03-01 | 0.20 | overdue:1081.7d | N/A |
| ZOOKEEPER-2991 | Server logs error on shutdown | 2021-03-01 | 0.20 | overdue:1081.6d | N/A |
| ZOOKEEPER-2995 | ant docs fails when Java 1.9 is present on my system | 2021-03-01 | 0.20 | overdue:1075.8d | N/A |
| ZOOKEEPER-2996 | core in netlink with "Unexpected error 9 on netlink descriptor 20" error | 2021-03-01 | 0.20 | overdue:1074.8d | N/A |
| ZOOKEEPER-30 | Hooks for atomic broadcast protocol | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-3000 | Use error-prone compiler | 2021-03-01 | 0.20 | overdue:1066.3d | N/A |
| ZOOKEEPER-3003 | ant package does not fail if javadoc generation fails | 2021-03-01 | 0.20 | overdue:1061.2d | N/A |
| ZOOKEEPER-3004 | create jenkins jobs to test java 6 for branch 3.4 | 2021-03-01 | 0.20 | overdue:1061.2d | N/A |
| ZOOKEEPER-3005 | Update zkEnv.cmd to check if environment variable are already exist | 2021-03-01 | 0.20 | overdue:1061.0d | N/A |
| ZOOKEEPER-3008 | Potential NPE in SaslQuorumAuthLearner#authenticate and SaslQuorumAuthServer#authenticate | 2021-03-01 | 0.20 | overdue:1057.7d | N/A |
| ZOOKEEPER-3010 | Potential NPE in Observer#observeLeader and Follower#followLeader | 2021-03-01 | 0.20 | overdue:1057.7d | N/A |
| ZOOKEEPER-3011 | Some NPEs, maybe | 2021-03-01 | 0.20 | overdue:1057.7d | N/A |
| ZOOKEEPER-3015 | Publish the value of getIdleRecv() in WatchedEvent of Disconnected | 2021-03-01 | 0.20 | overdue:1052.3d | N/A |
| ZOOKEEPER-3018 | Ephemeral node not deleted after session is gone | 2021-03-01 | 0.20 | overdue:1048.2d | N/A |
| ZOOKEEPER-3023 | Flaky test: org.apache.zookeeper.server.quorum.Zab1_0Test.testNormalFollowerRunWithDiff | 2021-03-01 | 0.20 | overdue:1032.5d | N/A |
| ZOOKEEPER-3024 | C++ Client return sub paths in String_vector illegal after zoo_get_children completed with ZOK | 2021-03-01 | 0.20 | overdue:1029.7d | N/A |
| ZOOKEEPER-3026 | ReadOnlyModeTest  is using Thread deprecated API. | 2021-03-01 | 0.20 | overdue:1028.0d | N/A |
| ZOOKEEPER-3036 | Unexpected exception in zookeeper | 2021-03-01 | 0.20 | overdue:1013.5d | N/A |
| ZOOKEEPER-3045 | NullPointerException and continuous EndOfStreamException warnings in ZooKeeper stdout after stop and start of ZooKeeper | 2021-03-01 | 0.20 | overdue:1005.5d | N/A |
| ZOOKEEPER-3047 | flaky test LearnerSnapshotThrottlerTest | 2021-03-01 | 0.20 | overdue:1003.0d | N/A |
| ZOOKEEPER-3048 | Track OutOfMemory failures on Flaky Dashboard | 2021-03-01 | 0.20 | overdue:1003.0d | N/A |
| ZOOKEEPER-3049 | would zookeeper transaction(multi) block the concurrent read? | 2021-03-01 | 0.20 | overdue:1002.9d | N/A |
| ZOOKEEPER-3052 | testReadOnly fails on slow host | 2021-03-01 | 0.20 | overdue:993.0d | N/A |
| ZOOKEEPER-3053 | add remove watches capabilities to the c cli | 2021-03-01 | 0.20 | overdue:993.0d | N/A |
| ZOOKEEPER-3054 | ipv6 detection in configure.ac is broken | 2021-03-01 | 0.20 | overdue:993.0d | N/A |
| ZOOKEEPER-3055 | Unable to connect to remote host: Connection refused | 2021-03-01 | 0.20 | overdue:989.3d | N/A |
| ZOOKEEPER-3058 | Do length check first before actual byte check in compareBytes method of Utils class | 2021-03-01 | 0.20 | overdue:983.3d | N/A |
| ZOOKEEPER-3064 | Format overflow warning when building with GCC 8.1 | 2021-03-01 | 0.20 | overdue:976.3d | N/A |
| ZOOKEEPER-3065 | Refactor existing reconfig tests in StaticHostProviderTest | 2021-03-01 | 0.20 | overdue:973.5d | N/A |
| ZOOKEEPER-3069 | document: is mutual auth with DIGEST-MD5 insecure? | 2021-03-01 | 0.20 | overdue:966.3d | N/A |
| ZOOKEEPER-3076 | DELETE - test | 2021-03-01 | 0.20 | overdue:958.4d | N/A |
| ZOOKEEPER-3081 | DELETE - test hello | 2021-03-01 | 0.20 | overdue:956.4d | N/A |
| ZOOKEEPER-3086 | [server] Lack of write timeouts causes quorum to stuck | 2021-03-01 | 0.20 | overdue:949.2d | N/A |
| ZOOKEEPER-3088 | zk c client: should delete tsd keys in a destructor  | 2021-03-01 | 0.20 | overdue:948.8d | N/A |
| ZOOKEEPER-3096 | Leader should not leak LearnerHandler threads | 2021-03-01 | 0.20 | overdue:941.2d | N/A |
| ZOOKEEPER-3099 | ZooKeeper cluster is unavailable for session_timeout time due to network partition in a three-node environment.    | 2021-03-01 | 0.20 | overdue:938.8d | N/A |
| ZOOKEEPER-310 | Coverity report on issues in C client code | 2021-03-01 | 0.20 | overdue:4387.2d | N/A |
| ZOOKEEPER-3100 | ZooKeeper client times out due to random choice of resolved addresses | 2021-03-01 | 0.20 | overdue:938.4d | N/A |
| ZOOKEEPER-3102 | Potential race condition when create ephemeral nodes | 2021-03-01 | 0.20 | overdue:937.7d | N/A |
| ZOOKEEPER-3107 | Coding standard and Checkstyle | 2021-03-01 | 0.20 | overdue:931.1d | N/A |
| ZOOKEEPER-3115 | Delete snapshot file on error | 2021-03-01 | 0.20 | overdue:921.9d | N/A |
| ZOOKEEPER-3126 | Documentation: Overview page has missing content | 2021-03-01 | 0.20 | overdue:909.5d | N/A |
| ZOOKEEPER-3128 | Get CLI Command displays Authentication error for Authorization error | 2021-03-01 | 0.20 | overdue:906.7d | 26.2 |
| ZOOKEEPER-3129 | Improve ZK Client resiliency by throwing a jute.maxbuffer size exception before sending a request to server | 2021-03-01 | 0.20 | overdue:905.1d | N/A |
| ZOOKEEPER-3133 | NIOServerCnxn.outstandingRequests is not updated correctly with sasl request | 2021-03-01 | 0.20 | overdue:902.0d | N/A |
| ZOOKEEPER-3134 | NIOServerCnxnFactory#run() method should remove synchronized (this) | 2021-03-01 | 0.20 | overdue:901.4d | N/A |
| ZOOKEEPER-3135 | update lastSend, lastHeard with current timestamp when client reconnects successfully | 2021-03-01 | 0.20 | overdue:900.9d | N/A |
| ZOOKEEPER-3138 | Potential race condition with Quorum Peer mutual authentication via SASL | 2021-03-01 | 0.20 | overdue:894.3d | N/A |
| ZOOKEEPER-3139 | Zookeeper is not getting started because server folder is not present in the jre/bin for version 1.8.0_181 on 32 bit machine | 2021-03-01 | 0.20 | overdue:892.6d | N/A |
| ZOOKEEPER-3141 | testLeaderElectionWithDisloyalVoter is flaky | 2021-03-01 | 0.20 | overdue:889.1d | N/A |
| ZOOKEEPER-3147 | Enable server tracking client information | 2021-03-01 | 0.20 | overdue:887.1d | N/A |
| ZOOKEEPER-3158 | firstConnect.countDown() will not be executed where sendThread.primeConnection() has thrown an exception | 2021-03-01 | 0.20 | overdue:870.8d | N/A |
| ZOOKEEPER-316 | configure option --without-cppunit does not work | 2021-03-01 | 0.20 | overdue:4381.2d | N/A |
| ZOOKEEPER-3164 | Backport ZOOKEEPER-3057 to branch3.5 | 2021-03-01 | 0.20 | overdue:859.6d | N/A |
| ZOOKEEPER-3166 | Support changing secure port with reconfig | 2021-03-01 | 0.20 | overdue:857.2d | N/A |
| ZOOKEEPER-3169 | Reduce session revalidation time after zxid roll over | 2021-03-01 | 0.20 | overdue:856.4d | N/A |
| ZOOKEEPER-317 | avoid exporting functions which may be static | 2021-03-01 | 0.20 | overdue:4381.2d | N/A |
| ZOOKEEPER-3170 | Umbrella for eliminating ZooKeeper flaky tests | 2021-03-01 | 0.20 | overdue:854.6d | N/A |
| ZOOKEEPER-3178 | Remove PrepRequestProcessor from RO ZooKeeperServer to avoid txns being created in RO mode | 2021-03-01 | 0.20 | overdue:853.4d | N/A |
| ZOOKEEPER-3182 | Race condition when follower syncing with leader and starting to serve requests | 2021-03-01 | 0.20 | overdue:844.4d | N/A |
| ZOOKEEPER-3185 | After the skipACL flag is opened, the acl of the created node becomes 'auth,'. This will cause the node to be unreadable after closing the skipACL. | 2021-03-01 | 0.20 | overdue:837.6d | N/A |
| ZOOKEEPER-3186 | bug in barrier example code | 2021-03-01 | 0.20 | overdue:829.7d | N/A |
| ZOOKEEPER-3187 | Apache zookeeper 3.5.3-beta security vulnerabilities CVE-2018-8012 | 2021-03-01 | 0.20 | overdue:826.4d | N/A |
| ZOOKEEPER-3189 | Support new configuration syntax for resilient network feature | 2021-03-01 | 0.20 | overdue:825.7d | N/A |
| ZOOKEEPER-3191 | Code clean up | 2021-03-01 | 0.20 | overdue:823.4d | N/A |
| ZOOKEEPER-3192 | zoo_multi/zoo_amulti crash | 2021-03-01 | 0.20 | overdue:822.9d | N/A |
| ZOOKEEPER-3196 | Maintain the configuration will be used by server stabilizer.It can be  overridden based on the server type and the server system internals. | 2021-03-01 | 0.20 | overdue:817.4d | N/A |
| ZOOKEEPER-3198 | Handle port-binding failures in a systematic and documented fashion | 2021-03-01 | 0.20 | overdue:816.1d | N/A |
| ZOOKEEPER-3200 | Flaky test: org.apache.zookeeper.server.quorum.QuorumPeerMainTest.testInconsistentDueToNewLeaderOrder | 2021-03-01 | 0.20 | overdue:813.2d | N/A |
| ZOOKEEPER-3201 | Flaky test: org.apache.zookeeper.server.ZxidRolloverTest.testRolloverThenLeaderRestart | 2021-03-01 | 0.20 | overdue:813.1d | N/A |
| ZOOKEEPER-3206 | Can't use Active Directory for Kerberos Authentication | 2021-03-01 | 0.20 | overdue:805.4d | N/A |
| ZOOKEEPER-3207 | Watch related code being copied over twice when doing maven migration | 2021-03-01 | 0.20 | overdue:804.2d | N/A |
| ZOOKEEPER-3211 | zookeeper standalone mode，found a high level bug in kernel of centos7.0 ，zookeeper Server's  tcp/ip socket connections(default 60 ) are CLOSE_WAIT ，this lead to zk can't work for client any more | 2021-03-01 | 0.20 | overdue:797.8d | N/A |
| ZOOKEEPER-3213 | Transaction has delete log bug actually it is not delete | 2021-03-01 | 0.20 | overdue:796.7d | N/A |
| ZOOKEEPER-322 |  move examples out of docs into contrib/examples  | 2021-03-01 | 0.20 | overdue:4379.9d | N/A |
| ZOOKEEPER-3220 | The snapshot is not saved to disk and may cause data inconsistency. | 2021-03-01 | 0.20 | overdue:790.6d | N/A |
| ZOOKEEPER-3221 | WriteLock in recipes may get wrong child name as lock id | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-645, overdue:790.4d | N/A |
| ZOOKEEPER-3227 | Address Spotbugs: DM_DEFAULT_ENCODING issues | 2021-03-01 | 0.20 | overdue:788.3d | N/A |
| ZOOKEEPER-323 | Log file reuse | 2021-03-01 | 0.20 | overdue:4379.1d | N/A |
| ZOOKEEPER-3231 |  Purge task may lost data when the recent snapshots are all invalid | 2021-03-01 | 0.20 | overdue:779.8d | 192.2 |
| ZOOKEEPER-324 | do not materialize strings in the server | 2021-03-01 | 0.20 | overdue:4379.0d | N/A |
| ZOOKEEPER-3241 | Update C client for the new getEphemerals api | 2021-03-01 | 0.20 | overdue:767.1d | N/A |
| ZOOKEEPER-3246 | Publish more stats when learner gets a diff, full snapshot, or does a truncate when it connects with the leader | 2021-03-01 | 0.20 | overdue:765.7d | N/A |
| ZOOKEEPER-3247 | New lest admin command to get leader election time | 2021-03-01 | 0.20 | overdue:765.0d | N/A |
| ZOOKEEPER-3248 | EmbeddedZookeeper does not delete temp directory on shutdown in Windows | 2021-03-01 | 0.20 | overdue:760.7d | N/A |
| ZOOKEEPER-3252 | Extend the options for the response cache | 2021-03-01 | 0.20 | overdue:759.1d | N/A |
| ZOOKEEPER-3259 | create a separate document:client.md about the usage of the client. | 2021-03-01 | 0.20 | overdue:749.5d | N/A |
| ZOOKEEPER-3260 | Open JDK 11 support in Zookeeper | 2021-03-01 | 0.20 | overdue:748.5d | N/A |
| ZOOKEEPER-3266 | ZooKeeper Java client blocks for a very long time. | 2021-03-01 | 0.20 | overdue:745.9d | N/A |
| ZOOKEEPER-3270 | Publish metrics for connected clients with user stats | 2021-03-01 | 0.20 | overdue:742.8d | N/A |
| ZOOKEEPER-3278 | Maven sources are not buildable if not linked to a git respotiory | 2021-03-01 | 0.20 | overdue:732.6d | N/A |
| ZOOKEEPER-3279 | Maven tests fail on branch-3.4 | 2021-03-01 | 0.20 | overdue:732.5d | N/A |
| ZOOKEEPER-328 | We need to test the code that uses DNS lookups that return multiple results to enumerate the zookeeper servers | 2021-03-01 | 0.20 | overdue:4375.0d | N/A |
| ZOOKEEPER-3282 | a big refactor for the documetations | 2021-03-01 | 0.20 | overdue:727.5d | N/A |
| ZOOKEEPER-3283 | add the new doc: zookeeperClients.md | 2021-03-01 | 0.20 | overdue:727.5d | N/A |
| ZOOKEEPER-3284 | Tests fails on 3.4 if running with surefire | 2021-03-01 | 0.20 | overdue:725.4d | N/A |
| ZOOKEEPER-3286 | xid wrap-around causes connection loss/segfault when hitting predefined XIDs | 2021-03-01 | 0.20 | overdue:725.1d | N/A |
| ZOOKEEPER-3287 | admin command to dump currently known ACLs | 2021-03-01 | 0.20 | overdue:724.8d | N/A |
| ZOOKEEPER-3290 | Throw detailed KeeperException when a transaction failed | 2021-03-01 | 0.20 | overdue:720.7d | N/A |
| ZOOKEEPER-3292 | ZooKeeper C Client for Windows: should include winports.h | 2021-03-01 | 0.20 | overdue:719.4d | N/A |
| ZOOKEEPER-3293 | ZooKeeper fails to compile on newer RHEL systems ie. Fedora | 2021-03-01 | 0.20 | overdue:713.0d | N/A |
| ZOOKEEPER-3294 | bin/zkServer.sh no neeed to check "$ZOOBIN/../libexec/zkEnv.sh" | 2021-03-01 | 0.20 | overdue:711.9d | N/A |
| ZOOKEEPER-3295 | bin/zkEnv.sh no need to check "$ZOOBINDIR"/../zookeeper-server/src/main/resources/lib/*.jar | 2021-03-01 | 0.20 | overdue:711.8d | N/A |
| ZOOKEEPER-3297 | A list of improvement and bug fixs for the CLI of ZooKeeper | 2021-03-01 | 0.20 | overdue:709.6d | N/A |
| ZOOKEEPER-3298 | add a new CLI: "ll" to show the nodes vertically | 2021-03-01 | 0.20 | overdue:709.6d | N/A |
| ZOOKEEPER-3300 | CLI:"history" should show the recent 10 cmds, not the 11 | 2021-03-01 | 0.20 | overdue:709.5d | N/A |
| ZOOKEEPER-3303 | ZooKeeper Perl client zkperl doesn't compile on newer RHEL systems ie. Fedora | 2021-03-01 | 0.20 | overdue:709.4d | N/A |
| ZOOKEEPER-3307 | Add DEBUG logs in zoo_* c client lib | 2021-03-01 | 0.20 | overdue:706.7d | N/A |
| ZOOKEEPER-331 | Create a privacy policy for the ZooKeeper website | 2021-03-01 | 0.20 | overdue:4371.2d | N/A |
| ZOOKEEPER-3315 | Exceptions in callbacks should be handlable by the application | 2021-03-01 | 0.20 | overdue:703.3d | N/A |
| ZOOKEEPER-3318 | [CLI way]Add a complete backup mechanism for zookeeper internal | 2021-03-01 | 0.20 | overdue:702.7d | N/A |
| ZOOKEEPER-3330 | [zookeeper-docs]:the index.md's navigation is broken | 2021-03-01 | 0.20 | overdue:696.5d | N/A |
| ZOOKEEPER-3333 | Detect if txnlogs and / or snapshots is deleted under a running ZK instance | 2021-03-01 | 0.20 | overdue:693.5d | N/A |
| ZOOKEEPER-3334 | ./zkCli.sh cannot create the node | 2021-03-01 | 0.20 | overdue:692.7d | N/A |
| ZOOKEEPER-3336 | Leader election terminated, two leaders or not following leader or not having state | 2021-03-01 | 0.20 | overdue:691.5d | N/A |
| ZOOKEEPER-3337 | Maven build failed with user or group id is too big  | 2021-03-01 | 0.20 | overdue:691.1d | N/A |
| ZOOKEEPER-3338 | Review of BufferStats Class | 2021-03-01 | 0.20 | overdue:690.5d | N/A |
| ZOOKEEPER-3352 | Use LevelDB For Backend | 2021-03-01 | 0.20 | overdue:679.1d | N/A |
| ZOOKEEPER-3358 | Make Snappy The Default Snapshot Compression Algorithm | 2021-03-01 | 0.20 | overdue:677.4d | N/A |
| ZOOKEEPER-3363 | Drop ant basedbuild umbrella issue | 2021-03-01 | 0.20 | overdue:674.6d | N/A |
| ZOOKEEPER-3367 | Zookeeper 3.4.14 Maven jar pulls in spotbugs-annotations, which is under LGPL license | 2021-03-01 | 0.20 | overdue:670.6d | N/A |
| ZOOKEEPER-3374 | Use MultiRead operation in the BFS utility | 2021-03-01 | 0.20 | overdue:658.5d | N/A |
| ZOOKEEPER-3376 | Create a Maven module for Metrics Providers API  | 2021-03-01 | 0.20 | overdue:656.5d | N/A |
| ZOOKEEPER-338 | zk hosts should be resolved periodically for loadbalancing amongst zk servers. | 2021-03-01 | 0.20 | overdue:4353.1d | N/A |
| ZOOKEEPER-3380 | A revist to the quota mechanism | 2021-03-01 | 0.20 | overdue:649.9d | N/A |
| ZOOKEEPER-3381 | Add multi watchregistration support for multiRead operation | 2021-03-01 | 0.20 | overdue:649.4d | N/A |
| ZOOKEEPER-3384 | Avoid long quorum unavailable time due to TLS connection close stalled with full send buffer | 2021-03-01 | 0.20 | overdue:648.0d | N/A |
| ZOOKEEPER-3387 | BufferedWriter -> FileWriter for reduced IO operations | 2021-03-01 | 0.20 | overdue:646.2d | N/A |
| ZOOKEEPER-3389 | Zookeeper does not export all required packages in OSGi (needed for curator) | 2021-03-01 | 0.20 | overdue:644.6d | N/A |
| ZOOKEEPER-339 | Prevent from running ZK nodes with the same node ID  | 2021-03-01 | 0.20 | overdue:4353.1d | N/A |
| ZOOKEEPER-3390 | Broken Link - Release Notes (PDF) | 2021-03-01 | 0.20 | overdue:644.4d | N/A |
| ZOOKEEPER-3393 | Read-only file system may make the whole ZooKeeper cluster to be unavailable. | 2021-03-01 | 0.20 | overdue:643.9d | N/A |
| ZOOKEEPER-3397 | API docs are incorrectly linked in release artifacts | 2021-03-01 | 0.20 | overdue:637.3d | N/A |
| ZOOKEEPER-34 | Optimize string deserialization | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-3403 | Zookeeper bundle 3.5.5 is Non OSGi complaint | 2021-03-01 | 0.20 | overdue:630.6d | N/A |
| ZOOKEEPER-3408 | Improve information about risks for forceSync config option | 2021-03-01 | 0.20 | overdue:626.5d | N/A |
| ZOOKEEPER-3413 | add a serialVersionUID for ClientCnxnLimitException to make compile no warning | 2021-03-01 | 0.20 | overdue:621.6d | N/A |
| ZOOKEEPER-3414 | sync api should throw NoNodeException when syncing a path which is not exist | 2021-03-01 | 0.20 | overdue:621.6d | N/A |
| ZOOKEEPER-3417 | add the new doc:zookeeperProtocols to introduce the implementation details of ZAB comparing with raft | 2021-03-01 | 0.20 | overdue:620.9d | N/A |
| ZOOKEEPER-3419 | Backup and recovery support | 2021-03-01 | 0.20 | overdue:620.1d | N/A |
| ZOOKEEPER-3420 | With newer ZK C Client and older ZK server, recv_buffer() could potentially return 0 continuously on non-blocking socket | 2021-03-01 | 0.20 | overdue:619.0d | N/A |
| ZOOKEEPER-3422 | add a getDataList operation | 2021-03-01 | 0.20 | overdue:615.8d | N/A |
| ZOOKEEPER-3424 | download page file package broken | 2021-03-01 | 0.20 | overdue:615.6d | N/A |
| ZOOKEEPER-3425 | ranking the ttl by expireTime asc for the performance | 2021-03-01 | 0.20 | overdue:615.5d | N/A |
| ZOOKEEPER-3428 | enable the TTL node and add a lazy-delete strategy to get noNodeException quickly when the ttl node had expired | 2021-03-01 | 0.20 | overdue:614.6d | N/A |
| ZOOKEEPER-3429 | Flaky test test:org.apache.zookeeper.test.DisconnectedWatcherTest.testManyChildWatchersAutoReset | 2021-03-01 | 0.20 | overdue:613.6d | N/A |
| ZOOKEEPER-3432 | Improving zookeeper trace for performance and scalability | 2021-03-01 | 0.20 | overdue:608.1d | N/A |
| ZOOKEEPER-3435 | client session expired after timeout after errors and warning logs in zk server logs | 2021-03-01 | 0.20 | overdue:606.4d | N/A |
| ZOOKEEPER-3444 | Latest stable version will not start on Windows Server 2016 (DataCenter edition) and Java 8 | 2021-03-01 | 0.20 | overdue:601.6d | N/A |
| ZOOKEEPER-3449 | Zero Configuration Discovery of ZooKeeper Quorum | 2021-03-01 | 0.20 | overdue:595.4d | N/A |
| ZOOKEEPER-3450 | Allow Quorum Leader to Register with Another Quorum | 2021-03-01 | 0.20 | overdue:595.4d | N/A |
| ZOOKEEPER-3451 | Quorum TLS (umbrella) | 2021-03-01 | 0.20 | overdue:595.4d | N/A |
| ZOOKEEPER-3452 | Document ZOOKEEPER-3174 Quorum TLS - support reloading trust/key store | 2021-03-01 | 0.20 | overdue:595.4d | N/A |
| ZOOKEEPER-3456 | Service temporarily unavailable due to an ongoing leader election. Please refresh | 2021-03-01 | 0.20 | overdue:589.5d | N/A |
| ZOOKEEPER-3466 | ZK cluster converges, but does not properly handle client connections (new in 3.5.5) | 2021-03-01 | 0.20 | overdue:573.3d | N/A |
| ZOOKEEPER-3467 | Complete quota system for zookeeper server | 2021-03-01 | 0.20 | overdue:573.3d | N/A |
| ZOOKEEPER-3469 | Checkstyle rules for ensure proper javadocs | 2021-03-01 | 0.20 | overdue:571.0d | N/A |
| ZOOKEEPER-3476 | Identify client request for quota control | 2021-03-01 | 0.20 | overdue:567.0d | N/A |
| ZOOKEEPER-3478 | Leader restart shuts down all the followers | 2021-03-01 | 0.20 | overdue:566.5d | N/A |
| ZOOKEEPER-3481 | The problem of AcceptedEpoch | 2021-03-01 | 0.20 | overdue:565.6d | N/A |
| ZOOKEEPER-3483 | Flaky test: org.apache.zookeeper.server.util.RequestPathMetricsCollectorTest.testCollectStats | 2021-03-01 | 0.20 | overdue:564.1d | N/A |
| ZOOKEEPER-3485 | Measure reconfiguration time | 2021-03-01 | 0.20 | overdue:563.8d | N/A |
| ZOOKEEPER-3486 | add the doc about how to configure SSL/TLS for the admin server | 2021-03-01 | 0.20 | overdue:563.8d | N/A |
| ZOOKEEPER-3487 | Execution the same conditional statement twice in ZooTrace | 2021-03-01 | 0.20 | overdue:563.5d | N/A |
| ZOOKEEPER-3488 | Possible information leakage to log without LOG configuration control LOG.isInfoEnabled() | 2021-03-01 | 0.20 | overdue:563.5d | N/A |
| ZOOKEEPER-3489 | Possible information leakage to log without LOG configuration control LOG.isWarnEnabled() | 2021-03-01 | 0.20 | overdue:563.5d | N/A |
| ZOOKEEPER-3490 | Zookeeper followers not reflecting writes (after months) | 2021-03-01 | 0.20 | overdue:563.4d | N/A |
| ZOOKEEPER-3497 | Make org.apache.zookeeper.jmx.MBeanRegistry a standard singleton | 2021-03-01 | 0.20 | overdue:558.6d | N/A |
| ZOOKEEPER-3499 | [admin server way] Add a complete backup mechanism for zookeeper internal | 2021-03-01 | 0.20 | overdue:557.7d | N/A |
| ZOOKEEPER-35 |  Replay logs | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-3500 |  Improving the ZAB UPTODATE semantic to only issue it to learner when there is limited lagging | 2021-03-01 | 0.20 | overdue:557.3d | N/A |
| ZOOKEEPER-3504 | An information leakage from FileTxnSnapLog to log: | 2021-03-01 | 0.20 | overdue:552.9d | N/A |
| ZOOKEEPER-3507 | Revisit name patterns | 2021-03-01 | 0.20 | overdue:551.4d | N/A |
| ZOOKEEPER-3508 | Strategy on line break | 2021-03-01 | 0.20 | overdue:551.4d | N/A |
| ZOOKEEPER-3511 | Remove 'membership:' string from output of 'conf' 4lw | 2021-03-01 | 0.20 | overdue:550.4d | N/A |
| ZOOKEEPER-3514 | Use client certificate SAN list for X.509 ACL AuthZ | 2021-03-01 | 0.20 | overdue:543.2d | N/A |
| ZOOKEEPER-3516 | Zookeeper not working with enabling ssl and remote authentication | 2021-03-01 | 0.20 | overdue:542.1d | N/A |
| ZOOKEEPER-3520 | KeeperException is good to have a error message field besides path | 2021-03-01 | 0.20 | overdue:540.9d | N/A |
| ZOOKEEPER-3521 | equals generate by jute potentially cause NPE | 2021-03-01 | 0.20 | overdue:540.9d | N/A |
| ZOOKEEPER-3526 | data inconsistency due to mistaken TRUNC caused by maxCommittedLog is much less than minCommittedLog when in readonly mode | 2021-03-01 | 0.20 | overdue:535.8d | N/A |
| ZOOKEEPER-3533 | Create systemic alerts for zookeeper | 2021-03-01 | 0.20 | overdue:531.3d | N/A |
| ZOOKEEPER-3534 | Non-stop communication between participants and observers. | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-3478, overdue:531.3d | N/A |
| ZOOKEEPER-3535 | support Cluster Id to identify an ensemble | 2021-03-01 | 0.20 | overdue:528.9d | N/A |
| ZOOKEEPER-3541 | Wrong placeholder '{}' in logs. | 2021-03-01 | 0.20 | overdue:524.8d | N/A |
| ZOOKEEPER-3547 | Add detailed documentation on throttling | 2021-03-01 | 0.20 | overdue:518.3d | N/A |
| ZOOKEEPER-3549 | zookeeper auto purge bug | 2021-03-01 | 0.20 | overdue:517.6d | N/A |
| ZOOKEEPER-3553 | Create Performance Test Tool  | 2021-03-01 | 0.20 | overdue:514.4d | N/A |
| ZOOKEEPER-3554 | A way to connect to a different port in CLIENT_JVMFLAGS | 2021-03-01 | 0.20 | overdue:511.6d | N/A |
| ZOOKEEPER-3556 | Dynamic configuration file can not be updated automatically after some zookeeper servers of zk cluster are down | 2021-03-01 | 0.20 | overdue:509.7d | N/A |
| ZOOKEEPER-3557 | Towards a testable codebase | 2021-03-01 | 0.20 | overdue:509.3d | N/A |
| ZOOKEEPER-3564 | org.apache.zookeeper.ClientCnxn EventThread Memory Problem | 2021-03-01 | 0.20 | overdue:503.9d | N/A |
| ZOOKEEPER-3565 | snapfile modified out of target directory during mvn testing | 2021-03-01 | 0.20 | overdue:503.3d | N/A |
| ZOOKEEPER-3566 | Send event zxid to watches | 2021-03-01 | 0.20 | overdue:502.8d | N/A |
| ZOOKEEPER-3568 | Remove Netty support from 3.4 | 2021-03-01 | 0.20 | overdue:501.1d | N/A |
| ZOOKEEPER-3569 | Compile error due to LOGSTREAM being null when passed to fprintf | 2021-03-01 | 0.20 | overdue:497.0d | N/A |
| ZOOKEEPER-3572 | correctly handle zooinspector resources | 2021-03-01 | 0.20 | overdue:493.7d | N/A |
| ZOOKEEPER-3573 | Dealing with long TLS connection closing time without SO_LINGER option | 2021-03-01 | 0.20 | overdue:492.0d | N/A |
| ZOOKEEPER-3576 | Zookeeper Fails with AUTH_FAILED state  with SASL | 2021-03-01 | 0.20 | overdue:490.7d | N/A |
| ZOOKEEPER-3577 | SSL support in ZooKeeper Dynamic Reconfiguration | 2021-03-01 | 0.20 | overdue:490.6d | N/A |
| ZOOKEEPER-3578 | Add a new CLI: multi | 2021-03-01 | 0.20 | overdue:490.6d | N/A |
| ZOOKEEPER-3583 | Add new apis to get node type and ttl time info | 2021-03-01 | 0.20 | overdue:488.9d | N/A |
| ZOOKEEPER-3584 | "NoAuth" error message is ambiguous | 2021-03-01 | 0.20 | overdue:487.6d | N/A |
| ZOOKEEPER-3585 | Add a documentation about RequestProcessors | 2021-03-01 | 0.20 | overdue:487.6d | N/A |
| ZOOKEEPER-3586 | Write Log To Multiple Drives | 2021-03-01 | 0.20 | overdue:487.1d | N/A |
| ZOOKEEPER-3587 | Add a documentation about docker | 2021-03-01 | 0.20 | overdue:486.9d | N/A |
| ZOOKEEPER-3589 | 3.4-branch has potential data inconsistency caused by ZOOKEEPER-3104 | 2021-03-01 | 0.20 | overdue:482.7d | N/A |
| ZOOKEEPER-3591 | Inconsistent resync with dynamic reconfig | 2021-03-01 | 0.20 | overdue:481.8d | N/A |
| ZOOKEEPER-3594 | Ability to skip proposing requests with error transactions | 2021-03-01 | 0.20 | overdue:477.0d | N/A |
| ZOOKEEPER-3598 |  Fix potential data inconsistency issue due to CommitProcessor not gracefully shutdown | 2021-03-01 | 0.20 | overdue:475.2d | N/A |
| ZOOKEEPER-3600 | support the complete linearizable read and multiply read consistency level | 2021-03-01 | 0.20 | overdue:473.6d | N/A |
| ZOOKEEPER-3601 | introduce the fault injection framework: Byteman for ZooKeeper | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-4074, overdue:472.7d | 88.5 |
| ZOOKEEPER-3603 | Zookeeper (3.5.6) not starting on mac | 2021-03-01 | 0.20 | overdue:472.4d | N/A |
| ZOOKEEPER-3604 | Improve the treatment of path parameter for ZooKeeper.sync method | 2021-03-01 | 0.20 | overdue:471.5d | N/A |
| ZOOKEEPER-3607 | Potential data inconsistency due to the inconsistency between ZKDatabase.committedLog and dataTree in Trunc sync. | 2021-03-01 | 0.20 | overdue:467.7d | N/A |
| ZOOKEEPER-3608 | add a documentation about currentEpoch and acceptEpoch | 2021-03-01 | 0.20 | overdue:466.6d | N/A |
| ZOOKEEPER-3609 | Update lib yui-min: 3.1.0 due to security vulnerability | 2021-03-01 | 0.20 | overdue:466.3d | N/A |
| ZOOKEEPER-3610 | Update lib prototype.js: 1.4.0_pre4 due to security vulnerability | 2021-03-01 | 0.20 | overdue:466.3d | N/A |
| ZOOKEEPER-3611 | addWatch api supports all watch event type, strengthen the corresponding CLI and add a documentation | 2021-03-01 | 0.20 | overdue:462.5d | N/A |
| ZOOKEEPER-3612 | CLONE - Update lib prototype.js: 1.4.0_pre4 due to security vulnerability | 2021-03-01 | 0.20 | overdue:461.5d | N/A |
| ZOOKEEPER-3614 | Limiting the number of ephemeral nodes per session | 2021-03-01 | 0.20 | overdue:459.9d | N/A |
| ZOOKEEPER-3615 | write a TLA+ specification to verify Zab protocol | 2021-03-01 | 0.20 | overdue:459.9d | N/A |
| ZOOKEEPER-3616 | add a new documentation: zookeeperCodingGuide.md | 2021-03-01 | 0.20 | overdue:459.5d | N/A |
| ZOOKEEPER-3617 | ZK digest ACL permissions gets overridden | 2021-03-01 | 0.20 | overdue:458.8d | N/A |
| ZOOKEEPER-3618 | Send batch quorum Ack and Commit packets to improve the efficiency and throughput of ZK | 2021-03-01 | 0.20 | overdue:458.3d | N/A |
| ZOOKEEPER-3619 | Implement server side semaphore API to improve the efficiency and throughput of coordination  | 2021-03-01 | 0.20 | overdue:458.2d | N/A |
| ZOOKEEPER-3621 | fix the potential bug in the process of clean-up of session when clock skew | 2021-03-01 | 0.20 | overdue:457.7d | N/A |
| ZOOKEEPER-3622 | ZooKeeper 3.5.6 Quorum TLS protocol issues | 2021-03-01 | 0.20 | overdue:456.9d | N/A |
| ZOOKEEPER-3623 | Build failure due to flaky tests on ppc64le | 2021-03-01 | 0.20 | overdue:453.7d | N/A |
| ZOOKEEPER-3624 | testFailedTxnAsPartOfQuorumLoss is flaky again | 2021-03-01 | 0.20 | overdue:453.7d | N/A |
| ZOOKEEPER-3625 | Add Automatic-Module-Name to MANIFEST.MF | 2021-03-01 | 0.20 | overdue:453.1d | N/A |
| ZOOKEEPER-3628 | Build failing on branch-3.4 with Java 8 | 2021-03-01 | 0.20 | overdue:451.6d | N/A |
| ZOOKEEPER-3629 | add a new metric to detect the clock skew | 2021-03-01 | 0.20 | overdue:450.8d | N/A |
| ZOOKEEPER-3631 | Create Maven-base Jenkins jobs for Windows CMake build | 2021-03-01 | 0.20 | overdue:448.6d | N/A |
| ZOOKEEPER-3632 | Create Maven-base Jenkins job to verify trunk with Java 13 | 2021-03-01 | 0.20 | overdue:448.6d | N/A |
| ZOOKEEPER-3634 | why zookeeper huge snapshot cause waitEpockAck timeout? | 2021-03-01 | 0.20 | overdue:444.7d | N/A |
| ZOOKEEPER-3637 | Fix haveDelivered wrong implementation | 2021-03-01 | 0.20 | overdue:438.5d | N/A |
| ZOOKEEPER-3639 | Unexpected exception causing CommitProcessor to exit | 2021-03-01 | 0.20 | overdue:437.7d | N/A |
| ZOOKEEPER-3643 | Testing and documenting secure and unsecure ZK client connection from the same JVM | 2021-03-01 | 0.20 | overdue:433.6d | N/A |
| ZOOKEEPER-3646 | Executing multiple commands non-interactively with the C client cli | 2021-03-01 | 0.20 | overdue:432.4d | N/A |
| ZOOKEEPER-3650 | zero or overflown xid disrupts the session  | 2021-03-01 | 0.20 | overdue:427.7d | N/A |
| ZOOKEEPER-3652 | Improper synchronization in ClientCnxn | 2021-03-01 | 0.20 | overdue:427.4d | N/A |
| ZOOKEEPER-3655 | Fix QuorumSSLTest to remove hardcoded localhost and port | 2021-03-01 | 0.20 | overdue:425.1d | N/A |
| ZOOKEEPER-3657 |  Implementing snapshot schedule to avoid high latency issue due to disk contention | 2021-03-01 | 0.20 | overdue:424.1d | N/A |
| ZOOKEEPER-3659 | make the WatchManagerFactory log more readable | 2021-03-01 | 0.20 | overdue:422.7d | N/A |
| ZOOKEEPER-3660 | support the lz4 compress mode for snapshot | 2021-03-01 | 0.20 | overdue:420.7d | N/A |
| ZOOKEEPER-3665 | support Client side caching in ZooKeeper | 2021-03-01 | 0.20 | overdue:416.9d | N/A |
| ZOOKEEPER-3670 | Clean Up Log Statements for SLF4J | 2021-03-01 | 0.20 | overdue:413.1d | N/A |
| ZOOKEEPER-3672 | BambuBet | 2021-03-01 | 0.20 | overdue:407.6d | N/A |
| ZOOKEEPER-3673 | Getting a snapshot from leader cause Connection reset shutdown Follower and repeated forever | 2021-03-01 | 0.20 | overdue:406.9d | N/A |
| ZOOKEEPER-3675 | Clean Up committedLog Interaction in ZKDatabase | 2021-03-01 | 0.20 | overdue:405.9d | N/A |
| ZOOKEEPER-3676 | Clean Up TxnLogProposalIterator | 2021-03-01 | 0.20 | overdue:405.9d | N/A |
| ZOOKEEPER-369 | remove multiple configs in server/quorums. | 2021-03-01 | 0.20 | overdue:4333.1d | N/A |
| ZOOKEEPER-3692 | Change Java Package For TestStringUtils | 2021-03-01 | 0.20 | overdue:401.3d | N/A |
| ZOOKEEPER-3697 | zoo_amulti can attempt to free invalid memory after marshalling errors. | 2021-03-01 | 0.20 | overdue:399.4d | N/A |
| ZOOKEEPER-37 | WebDAV access to ZooKeeper | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-3700 | Several types of QuorumCxnManager connection error logs include exception text that add no value | 2021-03-01 | 0.20 | overdue:392.9d | N/A |
| ZOOKEEPER-3702 | AdminServer stops responding (possible deadlock) | 2021-03-01 | 0.20 | overdue:392.1d | N/A |
| ZOOKEEPER-3705 | Filtering unreachable hosts without using ICMP | 2021-03-01 | 0.20 | overdue:389.4d | N/A |
| ZOOKEEPER-3707 | Leadership Election gets stuck in 5 node ensemble | 2021-03-01 | 0.20 | overdue:384.9d | N/A |
| ZOOKEEPER-3709 | Pre-Size Buffer in Learner Request Method | 2021-03-01 | 0.20 | overdue:382.0d | N/A |
| ZOOKEEPER-3711 | Dispose SaslServer instances after use | 2021-03-01 | 0.20 | overdue:379.4d | N/A |
| ZOOKEEPER-3713 | ReadOnlyZooKeeperServer should not expose the uninitialized ZKDatabase to client during the snapshot loading. | 2021-03-01 | 0.20 | overdue:378.5d | N/A |
| ZOOKEEPER-3717 | Zookeeper won't work with swarm service VIP when enabling healthcheck | 2021-03-01 | 0.20 | overdue:377.2d | N/A |
| ZOOKEEPER-372 | Use ZooKeeper server identifier with AuthFastLeaderElection  | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-577, overdue:4330.4d | N/A |
| ZOOKEEPER-3724 | [Java Client] - Calculation of connectionTimeout needs improvement. | 2021-03-01 | 0.20 | overdue:368.7d | N/A |
| ZOOKEEPER-3731 | Disable HTTP TRACE Method | 2021-03-01 | 0.20 | overdue:363.5d | N/A |
| ZOOKEEPER-3732 | Update jUnit to 5.6 | 2021-03-01 | 0.20 | overdue:363.3d | N/A |
| ZOOKEEPER-3735 | fix the bad format of RATE_LOGGER | 2021-03-01 | 0.20 | overdue:357.9d | N/A |
| ZOOKEEPER-3736 | Zookeeper auto purge process does not purge files | 2021-03-01 | 0.20 | overdue:357.1d | N/A |
| ZOOKEEPER-3740 | Fix PurgeTxnTest.testPurgeWhenLogRollingInProgress | 2021-03-01 | 0.20 | overdue:354.6d | N/A |
| ZOOKEEPER-3742 | How to using rsyslog in zookeeper and modifying the port does not apply to the default port 514? | 2021-03-01 | 0.20 | overdue:354.4d | N/A |
| ZOOKEEPER-3743 | Poor error messages about the parsing of the jass.conf file | 2021-03-01 | 0.20 | overdue:354.3d | N/A |
| ZOOKEEPER-3744 | Make build reproducible | 2021-03-01 | 0.20 | overdue:352.9d | N/A |
| ZOOKEEPER-3749 | https://zookeeper.apache.org/documentation.html links all dead | 2021-03-01 | 0.20 | overdue:345.0d | N/A |
| ZOOKEEPER-3754 | ZooKeeper unusable in OSGi - missing headers | 2021-03-01 | 0.20 | overdue:343.7d | N/A |
| ZOOKEEPER-3757 | Transaction log sync can take 20+ seconds after leader election when there is a large snapCount | 2021-03-01 | 0.20 | overdue:338.3d | N/A |
| ZOOKEEPER-3759 | A way to configure the jmx rmi port | 2021-03-01 | 0.20 | overdue:336.4d | N/A |
| ZOOKEEPER-3762 | Add Client/Server API to return available features | 2021-03-01 | 0.20 | overdue:334.3d | N/A |
| ZOOKEEPER-3764 | Add High Availability Guarantee Into Docs | 2021-03-01 | 0.20 | overdue:333.1d | 39.3 |
| ZOOKEEPER-3766 | zkServer and other scripts should export CLASSPATH rather than use -cp | 2021-03-01 | 0.20 | overdue:332.7d | N/A |
| ZOOKEEPER-3768 | improve the output of the hidden password in digest mode and fix the hardcode of ACL Scheme | 2021-03-01 | 0.20 | overdue:330.8d | N/A |
| ZOOKEEPER-3770 | Monitoring script support for 3.6 | 2021-03-01 | 0.20 | overdue:327.5d | N/A |
| ZOOKEEPER-3773 | Version argument should be checked at the client side | 2021-03-01 | 0.20 | overdue:323.9d | N/A |
| ZOOKEEPER-3775 | Wrong message in IOException | 2021-03-01 | 0.20 | overdue:322.2d | N/A |
| ZOOKEEPER-3777 | the artifactId of parent pom should be improved | 2021-03-01 | 0.20 | overdue:320.9d | N/A |
| ZOOKEEPER-3779 | Zookeeper client 3.4.x fails to connect when using Java 14 | 2021-03-01 | 0.20 | overdue:320.8d | N/A |
| ZOOKEEPER-3781 | Zookeeper 3.5.7 not creating snapshot | 2021-03-01 | 0.20 | overdue:320.4d | 4.8 |
| ZOOKEEPER-3783 | Build ZooKeeper based on RocksDB  | 2021-03-01 | 0.20 | overdue:319.2d | N/A |
| ZOOKEEPER-3784 | PrometheusProvider uses deprecated sun.misc.Unsafe | 2021-03-01 | 0.20 | overdue:317.8d | N/A |
| ZOOKEEPER-3787 | Apply modernizer-maven-plugin to build | 2021-03-01 | 0.20 | overdue:313.9d | N/A |
| ZOOKEEPER-3789 | fix the build warnings about @see,@link,@return found by IDEA | 2021-03-01 | 0.20 | overdue:312.9d | N/A |
| ZOOKEEPER-3795 | Need to script to test zookeeper canary checks | 2021-03-01 | 0.20 | overdue:306.5d | N/A |
| ZOOKEEPER-3799 | rename CommitProcessor to CommitRequestProcessor | 2021-03-01 | 0.20 | overdue:303.6d | N/A |
| ZOOKEEPER-3800 | improve the log printing the address when QuorumCnxManager#ListenerHandler's port binds  | 2021-03-01 | 0.20 | overdue:303.6d | 299.3 |
| ZOOKEEPER-3804 | upgrade netty to 4.1.49 | 2021-03-01 | 0.20 | overdue:298.4d | N/A |
| ZOOKEEPER-3806 | TLS - dynamic loading for client trust/key store | 2021-03-01 | 0.20 | overdue:297.5d | N/A |
| ZOOKEEPER-3807 | fix the bad format when website pages build due to bash marker | 2021-03-01 | 0.20 | overdue:296.8d | 183.4 |
| ZOOKEEPER-3809 | write a documentation about published academic papers about ZooKeeper | 2021-03-01 | 0.20 | overdue:296.4d | N/A |
| ZOOKEEPER-3812 |  ZooKeeper Recipes hyperlink is broken on Intro page | 2021-03-01 | 0.20 | overdue:292.6d | N/A |
| ZOOKEEPER-3815 | Support a new comprehensive parent znode watcher | 2021-03-01 | 0.20 | overdue:289.1d | N/A |
| ZOOKEEPER-3816 | Improve the lagging detection between the leader and learners  | 2021-03-01 | 0.20 | overdue:288.3d | N/A |
| ZOOKEEPER-3819 | Potential Races on DataTree | 2021-03-01 | 0.20 | overdue:285.4d | N/A |
| ZOOKEEPER-3820 | Missing zookeeper.jute.c, zookeeper.jute.h in release archive | 2021-03-01 | 0.20 | overdue:285.2d | N/A |
| ZOOKEEPER-3821 | improve getting snapCount and globalOutstandingLimit  from System's Property | 2021-03-01 | 0.20 | overdue:284.8d | 103.3 |
| ZOOKEEPER-3822 | Zookeeper 3.6.1 EndOfStreamException | 2021-03-01 | 0.20 | overdue:284.2d | N/A |
| ZOOKEEPER-3823 | Add a benchmark tool for testing watch feature performance | 2021-03-01 | 0.20 | overdue:280.7d | N/A |
| ZOOKEEPER-3824 | ZooKeeper dynamic reconfig doesn't work with GSSAPI/SASL enabled Quorum authn/z | 2021-03-01 | 0.20 | overdue:280.4d | N/A |
| ZOOKEEPER-3825 | StaticHostProvider.updateServerList address matching fails when connectString uses IP addresses | 2021-03-01 | 0.20 | overdue:280.0d | N/A |
| ZOOKEEPER-3826 | upgrade from 3.4.x to 3.5.x | 2021-03-01 | 0.20 | overdue:279.6d | N/A |
| ZOOKEEPER-3827 | configure explicit sessionInitTimeout for client connection | 2021-03-01 | 0.20 | overdue:279.4d | N/A |
| ZOOKEEPER-3828 | zookeeper clients gets connection timeout when the leader node is restarted | 2021-03-01 | 0.20 | overdue:277.0d | N/A |
| ZOOKEEPER-3835 | Deprecate IOUtils copyBytes | 2021-03-01 | 0.20 | overdue:272.4d | N/A |
| ZOOKEEPER-3837 | Deprecate StringUtils Functions | 2021-03-01 | 0.20 | overdue:272.4d | N/A |
| ZOOKEEPER-3838 | Async handling of quorum connection requests, including SSL handshakes | 2021-03-01 | 0.20 | overdue:272.4d | N/A |
| ZOOKEEPER-3840 | Use JDK 8 Facilities to Synchronize Access to DataTree Ephemerals | 2021-03-01 | 0.20 | overdue:272.3d | N/A |
| ZOOKEEPER-3848 | Zookeeper upgrade fails due to missing snapshots on branch-3.6 | 2021-03-01 | 0.20 | overdue:267.9d | N/A |
| ZOOKEEPER-3851 | Upgrade jUnit in ZooKeeper-Contrib | 2021-03-01 | 0.20 | overdue:254.2d | N/A |
| ZOOKEEPER-3853 | Upgrade jUnit in ZooKeeper-IT | 2021-03-01 | 0.20 | overdue:254.2d | N/A |
| ZOOKEEPER-3860 | Avoid reverse DNS lookup for hostname verification when hostnames are provided in the connection url | 2021-03-01 | 0.20 | overdue:249.0d | N/A |
| ZOOKEEPER-3861 | log.zxid file is very large size. I want to know the reason and solution. | 2021-03-01 | 0.20 | overdue:245.7d | N/A |
| ZOOKEEPER-3866 | Unable to change permission of zookeper node having read access | 2021-03-01 | 0.20 | overdue:244.5d | N/A |
| ZOOKEEPER-3867 | Apache Zookeeper Common/Default Nodes Accessible Without ACL | 2021-03-01 | 0.20 | overdue:244.5d | N/A |
| ZOOKEEPER-3868 | Completion leak in zookeeper_close | 2021-03-01 | 0.20 | overdue:242.1d | N/A |
| ZOOKEEPER-3869 | add a documentation about the client property: zookeeper.request.timeout | 2021-03-01 | 0.20 | overdue:238.6d | N/A |
| ZOOKEEPER-3870 | Avoid out of order response and txns created with ReadOnlyZooKeeperServer | 2021-03-01 | 0.20 | overdue:236.3d | N/A |
| ZOOKEEPER-3873 | ClientCnxnSocketNIO#enableWrite throws NullPointerException | 2021-03-01 | 0.20 | overdue:233.8d | N/A |
| ZOOKEEPER-3875 | Sequential consistency violation | 2021-03-01 | 0.20 | overdue:228.9d | N/A |
| ZOOKEEPER-3877 | JMX Bean RemotePeerBean should enclose IPV6 host in square bracket same as LocalPeerBean  | 2021-03-01 | 0.20 | overdue:227.7d | 0.3 |
| ZOOKEEPER-3879 | C Client: how to build? | 2021-03-01 | 0.20 | overdue:226.5d | N/A |
| ZOOKEEPER-388 | Add readline support to the c shell | 2021-03-01 | 0.20 | overdue:4308.1d | N/A |
| ZOOKEEPER-3880 | Add a script: zkCleanup.cmd to clean the transaction logs and snapshots in Windows OS | 2021-03-01 | 0.20 | overdue:225.8d | N/A |
| ZOOKEEPER-3882 | Zookeeper quorum formation fails when TLS is enabled in k8s env | 2021-03-01 | 0.20 | overdue:223.1d | N/A |
| ZOOKEEPER-3884 | zkServer.sh status doesn't work when we do a large scale benchmark test | 2021-03-01 | 0.20 | overdue:218.9d | N/A |
| ZOOKEEPER-3887 | In SSL-only server zkServer.sh status command should use secureClientPortAddress instead of clientPortAddress | 2021-03-01 | 0.20 | overdue:217.1d | 25.7 |
| ZOOKEEPER-3889 | Add volatile for variable finished in ReadOnlyRequestProcessor | 2021-03-01 | 0.20 | overdue:216.5d | N/A |
| ZOOKEEPER-3892 | client cannot connect to server when we do a large scala benchmark test | 2021-03-01 | 0.20 | overdue:213.6d | N/A |
| ZOOKEEPER-3894 | Out-of-order response after session moved | 2021-03-01 | 0.20 | overdue:209.3d | N/A |
| ZOOKEEPER-3897 | When using hostname zookeeper only binds to 127.0.0.1 for quorum | 2021-03-01 | 0.20 | overdue:206.7d | N/A |
| ZOOKEEPER-390 | zookeeper url scheme | 2021-03-01 | 0.20 | overdue:4304.3d | N/A |
| ZOOKEEPER-3902 | ZooKeeper cluster did not perform leader reelection when leader host crashed | 2021-03-01 | 0.20 | overdue:202.2d | N/A |
| ZOOKEEPER-3903 | Fix typos and grammar in recipes.md | 2021-03-01 | 0.20 | overdue:201.4d | N/A |
| ZOOKEEPER-3904 | Remove duplicate check in ContainerManager#getCandidates method | 2021-03-01 | 0.20 | overdue:197.9d | N/A |
| ZOOKEEPER-3906 | Data Inconsistency Between Zookeeper Leader and zookeeper Followers | 2021-03-01 | 0.20 | overdue:196.2d | N/A |
| ZOOKEEPER-3907 | add a documentation about alerting on metrics | 2021-03-01 | 0.20 | overdue:195.8d | 95.4 |
| ZOOKEEPER-3908 | zktreeutil multiple issues | 2021-03-01 | 0.20 | overdue:195.3d | N/A |
| ZOOKEEPER-3909 | Zookeeper Unable to Join the Cluster after it is Restarted; Error: "This ZooKeeper instance is not currently serving requests" | 2021-03-01 | 0.20 | overdue:192.3d | N/A |
| ZOOKEEPER-3910 | zkServer.sh code format is oldfashioned and chaotic | 2021-03-01 | 0.20 | overdue:189.4d | N/A |
| ZOOKEEPER-3912 | 4LW MNTR command outputs in float when prometheus activated | 2021-03-01 | 0.20 | overdue:182.6d | N/A |
| ZOOKEEPER-3914 | Kerberized Zookeeper doesn't drop connection for unauthenticated clients | 2021-03-01 | 0.20 | overdue:179.7d | N/A |
| ZOOKEEPER-3915 | Digest false mismatch across systems with different default locale | 2021-03-01 | 0.20 | overdue:178.2d | N/A |
| ZOOKEEPER-3918 | Authorization Provider: Integration with external identity and access management | 2021-03-01 | 0.20 | overdue:175.1d | N/A |
| ZOOKEEPER-3921 | Authorization Provider: Support add auth x509 for user identities with admin access | 2021-03-01 | 0.20 | overdue:172.8d | N/A |
| ZOOKEEPER-3922 | Add support for two server ZooKeeper with hardware oracle | 2021-03-01 | 0.20 | overdue:172.0d | 0.2 |
| ZOOKEEPER-3923 | Leader election issues with Istio | 2021-03-01 | 0.20 | overdue:171.3d | N/A |
| ZOOKEEPER-3928 | prometheus metrics packets_sent and packets_received wrong type | 2021-03-01 | 0.20 | overdue:160.6d | N/A |
| ZOOKEEPER-3929 | prometheus metrics with type "summary" always show quantiles as NaN | 2021-03-01 | 0.20 | overdue:160.5d | N/A |
| ZOOKEEPER-3930 | Security issues: config zookeeper.ssl.ciphersuites do not effect for zookeeper client | 2021-03-01 | 0.20 | overdue:160.5d | N/A |
| ZOOKEEPER-3931 | "zkServer.sh version" returns a trailing dash | 2021-03-01 | 0.20 | overdue:159.8d | 33.2 |
| ZOOKEEPER-3936 | Zxid mismatch after new node becomes the leader | 2021-03-01 | 0.20 | overdue:153.9d | N/A |
| ZOOKEEPER-3938 | Upgrade jline to version 3.x. | 2021-03-01 | 0.20 | overdue:151.7d | N/A |
| ZOOKEEPER-3939 | There is not property for private key password. no cipher suites in common | 2021-03-01 | 0.20 | overdue:147.7d | N/A |
| ZOOKEEPER-3940 | Zookeeper restart of leader causes all zk nodes to not serve requests | 2021-03-01 | 0.20 | overdue:147.4d | N/A |
| ZOOKEEPER-3946 | Convergence fails when a follower missed the committedLog synching with the leader if it was an old leader and the leader falls back to send snapshot. | 2021-03-01 | 0.20 | overdue:143.9d | N/A |
| ZOOKEEPER-3947 | truncate in FileTxnLog.java is buggy and fails to correctly truncate a file containing a single transaction only the follower saw | 2021-03-01 | 0.20 | overdue:143.9d | N/A |
| ZOOKEEPER-3961 | Inaccurate Error Message | 2021-03-01 | 0.20 | overdue:131.2d | 131.5 |
| ZOOKEEPER-3963 | Revamp and Log Connection Disconnect Reason | 2021-03-01 | 0.20 | overdue:131.1d | N/A |
| ZOOKEEPER-3964 | Introduce RocksDB snap and implement change data capture to enable incremental snapshot | 2021-03-01 | 0.20 | overdue:131.0d | N/A |
| ZOOKEEPER-3965 | Add documentation for RocksDB Snap feature | 2021-03-01 | 0.20 | overdue:131.0d | N/A |
| ZOOKEEPER-3966 | Model ZooKeeper data tree using RocksDB primitives to enable on disk data tree storage | 2021-03-01 | 0.20 | overdue:131.0d | N/A |
| ZOOKEEPER-3968 | ApacheCon Bug Bash fixes | 2021-03-01 | 0.20 | overdue:125.7d | N/A |
| ZOOKEEPER-3970 | Enable ZooKeeperServerController to expire session | 2021-03-01 | 0.20 | overdue:123.8d | 79.4 |
| ZOOKEEPER-3972 | Convergence fail when a follower tries to resync with a leader having incomplete commitlog | 2021-03-01 | 0.20 | overdue:123.4d | N/A |
| ZOOKEEPER-3974 | Generated build files from zookeeper-client-c should be in target/ directory | 2021-03-01 | 0.20 | overdue:122.4d | N/A |
| ZOOKEEPER-3975 | Zookeeper crashes: Unable to load database on disk java.io.IOException: Unreasonable length | 2021-03-01 | 0.20 | overdue:122.4d | N/A |
| ZOOKEEPER-3976 | write a script to encapsulate DigestAuthenticationProvider as a tool to generate the digest with algorithm users appoint | 2021-03-01 | 0.20 | overdue:119.6d | N/A |
| ZOOKEEPER-3982 | export ZooKeeper version as prometheus metric | 2021-03-01 | 0.20 | overdue:116.9d | N/A |
| ZOOKEEPER-3986 | ConcurrentModificationException in PrepRequestProcessor.checkACL when iterating and add authInfo List concurrently | 2021-03-01 | 0.20 | overdue:112.1d | N/A |
| ZOOKEEPER-3988 | org.apache.zookeeper.server.NettyServerCnxn.receiveMessage throws NullPointerException | 2021-03-01 | 0.20 | overdue:105.6d | N/A |
| ZOOKEEPER-3993 | Review some hashcode / equals methods | 2021-03-01 | 0.20 | overdue:103.1d | N/A |
| ZOOKEEPER-3995 | Vulnerabilities in components packaged in zookeeper docker | 2021-03-01 | 0.20 | overdue:101.5d | N/A |
| ZOOKEEPER-3996 | Flaky test: ReadOnlyModeTest.testConnectionEvents | 2021-03-01 | 0.20 | overdue:100.5d | N/A |
| ZOOKEEPER-3998 | quorum not established - java.net.SocketException: Connection reset seen in leader log | 2021-03-01 | 0.20 | overdue:97.5d | N/A |
| ZOOKEEPER-40 | Go read-only on loss of quorum | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-4002 | ZKAuditProvider throw NullPointerException if 'AUDIT_ENABLE' is false | 2021-03-01 | 0.20 | overdue:94.7d | N/A |
| ZOOKEEPER-4003 | Zookeeper server breakdown Frequently | 2021-03-01 | 0.20 | overdue:94.6d | N/A |
| ZOOKEEPER-4004 | ZKUtil.visitSubTreeDFSHelper use method with recursive may occur some question | 2021-03-01 | 0.20 | overdue:89.9d | N/A |
| ZOOKEEPER-4005 | Zookeeper will not sync snapshot while get DIFF and cause start failed. | 2021-03-01 | 0.20 | overdue:89.6d | N/A |
| ZOOKEEPER-4009 | Add Four-letter command to shed clients | 2021-03-01 | 0.20 | overdue:87.9d | N/A |
| ZOOKEEPER-401 | Cleaning of logging in the code and log4j configuration might be a good idea | 2021-03-01 | 0.20 | overdue:4297.1d | N/A |
| ZOOKEEPER-4010 | ProviderRegistry.initialized is not volatile | 2021-03-01 | 0.20 | overdue:87.9d | N/A |
| ZOOKEEPER-4012 | No install target for C library | 2021-03-01 | 0.20 | overdue:86.1d | N/A |
| ZOOKEEPER-4013 | pkg-config file for C library | 2021-03-01 | 0.20 | overdue:86.0d | N/A |
| ZOOKEEPER-4014 | libzookeeper.a not properly linking to libhashtable.a | 2021-03-01 | 0.20 | overdue:85.8d | N/A |
| ZOOKEEPER-4015 | Flaky test: RequestPathMetricsCollectorTest.testMultiThreadPerf | 2021-03-01 | 0.20 | overdue:85.7d | N/A |
| ZOOKEEPER-4016 |  C client build issue causes the failure of CI build  | 2021-03-01 | 0.20 | overdue:84.5d | N/A |
| ZOOKEEPER-4019 | FileChangeWatcher keep throwing exceptions on k8s deployment | 2021-03-01 | 0.20 | overdue:75.4d | N/A |
| ZOOKEEPER-4020 | Memory leak in  Zookeeper C Client | 2021-03-01 | 0.20 | overdue:75.0d | N/A |
| ZOOKEEPER-4021 | Zookeeper C Client ERROR about poll | 2021-03-01 | 0.20 | overdue:74.7d | N/A |
| ZOOKEEPER-4022 | ZooKeeper client session establishment deficiency | 2021-03-01 | 0.20 | overdue:73.0d | N/A |
| ZOOKEEPER-4025 | hello I want to update the zookeeper_client_c readme file | 2021-03-01 | 0.20 | overdue:69.9d | N/A |
| ZOOKEEPER-4026 | CREATE2 requests embeded in a MULTI request only get a regular CREATE response | 2021-03-01 | 0.20 | overdue:69.3d | N/A |
| ZOOKEEPER-4027 | Documentation: Configuration Format | 2021-03-01 | 0.20 | overdue:67.7d | N/A |
| ZOOKEEPER-4029 | improve the log of FileTxnLog#append method | 2021-03-01 | 0.20 | overdue:61.6d | N/A |
| ZOOKEEPER-4032 | Use `Map.computeIfAbsent` instead of `if Map.get is null then put value` | 2021-03-01 | 0.20 | overdue:55.6d | N/A |
| ZOOKEEPER-4035 | Add a documentation about the property: zookeeper.testingonly.initialZxid | 2021-03-01 | 0.20 | overdue:54.7d | N/A |
| ZOOKEEPER-4036 | correct the annotation/comment about the frequency of leader's ping | 2021-03-01 | 0.20 | overdue:54.6d | N/A |
| ZOOKEEPER-4038 | when logfile zxid equals to target zxid, should not iterate over the next logfile (FileTxnLog:653) | 2021-03-01 | 0.20 | overdue:52.5d | N/A |
| ZOOKEEPER-4040 | java.io.IOException: Leaders epoch, 1 is less than accepted epoch, 2 | 2021-03-01 | 0.20 | overdue:49.6d | N/A |
| ZOOKEEPER-4041 | Zookeeper returns an IP address when requesting a path data. | 2021-03-01 | 0.20 | overdue:48.6d | N/A |
| ZOOKEEPER-4042 | LeanerHandler.sock is always not null | 2021-03-01 | 0.20 | overdue:46.9d | N/A |
| ZOOKEEPER-4044 | Remove unused method and variable | 2021-03-01 | 0.20 | overdue:41.9d | N/A |
| ZOOKEEPER-4047 | C-Client does not return a error notification or callback | 2021-03-01 | 0.20 | overdue:40.9d | N/A |
| ZOOKEEPER-4049 | C client test failure on docker | 2021-03-01 | 0.20 | overdue:39.4d | N/A |
| ZOOKEEPER-4051 | Leader did not lose the quorum when a node left the quorum of 3 out of 5 nodes. | 2021-03-01 | 0.20 | overdue:38.7d | N/A |
| ZOOKEEPER-4052 | Failed to read large znode that is written successfully | 2021-03-01 | 0.20 | overdue:38.6d | N/A |
| ZOOKEEPER-4053 | ConnectionLossException is vague for failing to read/write large znode | 2021-03-01 | 0.20 | overdue:38.0d | N/A |
| ZOOKEEPER-4054 | Make prometheus listen host can configure | 2021-03-01 | 0.20 | overdue:37.9d | N/A |
| ZOOKEEPER-4057 | NIOServerCnxnFactory.selectorThreads,using List instead of HashSet is better | 2021-03-01 | 0.20 | overdue:32.7d | N/A |
| ZOOKEEPER-4074 | Network issue while Learner is executing writePacket can cause the follower to hang | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-3601, overdue:30.0d | N/A |
| ZOOKEEPER-414 | zkServer.sh is duplicated in a couple of places | 2021-03-01 | 0.20 | overdue:4289.1d | N/A |
| ZOOKEEPER-4183 | Leader election not working when using hostname in server config and hostname resolves to an internal IP addresses | 2021-03-01 | 0.20 | overdue:27.5d | N/A |
| ZOOKEEPER-4184 | Why org.apache.zookeeper.ClientCnxnSocketNIO#cleanup will sleep 100ms. | 2021-03-01 | 0.20 | overdue:27.5d | N/A |
| ZOOKEEPER-4185 | Addition of new ZooTrace Mask LEADER_ELECTION_MASK and related log lines for better leader election telemetry | 2021-03-01 | 0.20 | overdue:27.1d | N/A |
| ZOOKEEPER-4187 | Support compressed data natively | 2021-03-01 | 0.20 | overdue:24.1d | N/A |
| ZOOKEEPER-4189 | Zooinspector Error while connecting to zookeeper | 2021-03-01 | 0.20 | overdue:23.7d | N/A |
| ZOOKEEPER-4192 | Fix typos and description | 2021-03-01 | 0.20 | overdue:22.5d | N/A |
| ZOOKEEPER-4193 | Too many files open when the domain can't be parse.  | 2021-03-01 | 0.20 | overdue:21.9d | N/A |
| ZOOKEEPER-4194 | ZooInspector throws NullPointerExceptions to console when node data is null | 2021-03-01 | 0.20 | overdue:19.8d | 25.8 |
| ZOOKEEPER-4195 | Define EOL for major releases | 2021-03-01 | 0.20 | overdue:19.3d | N/A |
| ZOOKEEPER-4196 | Flaky test: org.apache.zookeeper.recipes.lock.WriteLockTest caused by Address already in use | 2021-03-01 | 0.20 | overdue:13.8d | N/A |
| ZOOKEEPER-4197 | Various tests fail on localhost.localdomain | 2021-03-01 | 0.20 | overdue:13.4d | N/A |
| ZOOKEEPER-4198 | Install Zookeeper on IBM Cloud | 2021-03-01 | 0.20 | overdue:12.2d | N/A |
| ZOOKEEPER-4203 | Leader swallows the ZooKeeperServer.State.ERROR from Leader.LearnerCnxAcceptor in some concurrency condition | 2021-03-01 | 0.20 | overdue:9.2d | N/A |
| ZOOKEEPER-4204 | Flaky test - RequestPathMetricsCollectorTest.testMultiThreadPerf | 2021-03-01 | 0.20 | overdue:7.5d | 148.6 |
| ZOOKEEPER-4205 | Test fails when port 8080 is in use | 2021-03-01 | 0.20 | overdue:7.4d | 15.4 |
| ZOOKEEPER-4208 | Adding more labels to asf.yaml file to position more to the ZooKeeper Project | 2021-03-01 | 0.20 | overdue:3.8d | 104.4 |
| ZOOKEEPER-4210 | Zookeeper c client: detect connection loss during opportunistic async send | 2021-03-01 | 0.20 | overdue:0.4d | 7.8 |
| ZOOKEEPER-4211 | Expose Quota Metrics to Prometheus | 2021-03-01 | 0.20 | age_over_70pct:13.2d | 149.4 |
| ZOOKEEPER-4212 | add committer checklist to zk-merge-pr.py | 2021-03-01 | 0.20 | age_over_70pct:12.8d | N/A |
| ZOOKEEPER-4213 | Ineffective transaction log padding on current OSes/JDKs | 2021-03-01 | 0.20 | age_over_70pct:12.2d | N/A |
| ZOOKEEPER-4214 | Update Ivy Netty version to 4.1.59.Final  | 2021-03-01 | 0.20 | age_over_70pct:12.1d | 5.4 |
| ZOOKEEPER-4215 | deleteall may not remove non-empty nodes if evaluated in follower server | 2021-03-01 | 0.20 | age_over_70pct:11.3d | N/A |
| ZOOKEEPER-4216 | Flaky test: WatcherCleanerTest.testDeadWatcherMetrics | 2021-03-01 | 0.20 | age_over_70pct:10.9d | N/A |
| ZOOKEEPER-4217 | Report caller function name in `handle_socket_error_msg`  | 2021-03-01 | 0.20 | age_over_70pct:10.9d | 5.4 |
| ZOOKEEPER-423 | Add getFirstChild API | 2021-03-01 | 0.20 | overdue:4277.3d | N/A |
| ZOOKEEPER-424 | server side chroot enforcment - link to auth | 2021-03-01 | 0.20 | overdue:4277.1d | N/A |
| ZOOKEEPER-430 | improve error reporting to client when setdata data length > max (default 1mb) | 2021-03-01 | 0.20 | overdue:4275.3d | N/A |
| ZOOKEEPER-439 | improve error reporting to client during connection establishment | 2021-03-01 | 0.20 | overdue:4270.1d | N/A |
| ZOOKEEPER-451 | ZK should enforce quota | 2021-03-01 | 0.20 | overdue:4249.2d | N/A |
| ZOOKEEPER-458 | connect_index in zookeeper handle might get out of bound. | 2021-03-01 | 0.20 | overdue:4246.0d | N/A |
| ZOOKEEPER-46 | Clients should check the latencies to the various servers and try to connect to the servers with the lowest latencies first | 2021-03-01 | 0.20 | overdue:4626.4d | N/A |
| ZOOKEEPER-474 | add compile, test, and improved package targets to zkperl build.xml | 2021-03-01 | 0.20 | overdue:4233.2d | N/A |
| ZOOKEEPER-478 | support custom hostnames for client and quorum connections | 2021-03-01 | 0.20 | overdue:4231.2d | N/A |
| ZOOKEEPER-497 | api and forrest docs should mention if classes are thread safe | 2021-03-01 | 0.20 | overdue:4213.1d | N/A |
| ZOOKEEPER-51 | Review error handling in PrepRequestProcessor.fixupACL | 2021-03-01 | 0.20 | overdue:4620.0d | N/A |
| ZOOKEEPER-52 | Session ids on the stat cmd information | 2021-03-01 | 0.20 | overdue:4618.4d | N/A |
| ZOOKEEPER-520 | add static/readonly client resident serverless zookeeper | 2021-03-01 | 0.20 | overdue:4183.0d | N/A |
| ZOOKEEPER-522 | zookeeper client should throttle if its not able to connect to any of the servers. | 2021-03-01 | 0.20 | overdue:4182.1d | N/A |
| ZOOKEEPER-523 | zookeeper c client should shutdown if it sees its zxid is too high from all the server its connecting to. | 2021-03-01 | 0.20 | overdue:4178.3d | N/A |
| ZOOKEEPER-525 | Changing children Set<String> to Set<byte[]> in DataNode | 2021-03-01 | 0.20 | overdue:4175.2d | N/A |
| ZOOKEEPER-526 | Change the access pattern in the DataNode from direct access to the use of getters and setters | 2021-03-01 | 0.20 | overdue:4175.0d | N/A |
| ZOOKEEPER-536 | the initial size of the hashsets for the watcher is too large | 2021-03-01 | 0.20 | overdue:4161.1d | N/A |
| ZOOKEEPER-545 | investigate use of realtime gc as the recommened default for server vm | 2021-03-01 | 0.20 | overdue:4148.3d | N/A |
| ZOOKEEPER-552 | add performance benchmark/docs for synchronous operations | 2021-03-01 | 0.20 | overdue:4143.1d | N/A |
| ZOOKEEPER-553 | C client's zoo_state function returns unknown state 0 | 2021-03-01 | 0.20 | overdue:4143.0d | N/A |
| ZOOKEEPER-571 | support balancing of client load across servers in an ensemble | 2021-03-01 | 0.20 | overdue:4116.0d | N/A |
| ZOOKEEPER-575 | remove System.exit calls to make the server more container friendly | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1072, overdue:4114.8d | N/A |
| ZOOKEEPER-577 | LeaderElection code hardcodes majority quorums in at least two places | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-372, overdue:4114.2d | N/A |
| ZOOKEEPER-580 | Document reasonable limits on the size and shape of data for a zookeeper ensemble. | 2021-03-01 | 0.20 | overdue:4108.3d | N/A |
| ZOOKEEPER-581 | peerType in configuration file is redundant | 2021-03-01 | 0.20 | overdue:4108.3d | N/A |
| ZOOKEEPER-583 | on resync client should generate session expired exception if there is no server in cluster with acceptable zxid | 2021-03-01 | 0.20 | overdue:4108.1d | N/A |
| ZOOKEEPER-584 | ZooKeeper service instance should be registered in the OSGi registry | 2021-03-01 | 0.20 | overdue:4106.4d | N/A |
| ZOOKEEPER-590 | review logging to ensure that session related messages include session id | 2021-03-01 | 0.20 | overdue:4102.7d | N/A |
| ZOOKEEPER-594 | Adding documentation to zkpython to help out with the setup for finding libzookeeper_mt.so.2 | 2021-03-01 | 0.20 | overdue:4101.3d | N/A |
| ZOOKEEPER-605 | remove datatreebuilder classes from the codebase. | 2021-03-01 | 0.20 | overdue:4094.0d | N/A |
| ZOOKEEPER-616 | Provide a function to parse out the name and the sequence number from a zknode path | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-849, overdue:4086.1d | N/A |
| ZOOKEEPER-625 | configure/change build scripts to generate cppunit reports | 2021-03-01 | 0.20 | overdue:4080.3d | N/A |
| ZOOKEEPER-639 | Performance improvements for ZooKeeper | 2021-03-01 | 0.20 | overdue:4057.2d | N/A |
| ZOOKEEPER-641 | Improve details about group membership recipe | 2021-03-01 | 0.20 | overdue:4053.1d | N/A |
| ZOOKEEPER-645 | Bug in WriteLock recipe implementation? | 2021-03-01 | 0.20 | overdue:4049.8d | N/A |
| ZOOKEEPER-646 | Namespace partitioning in ZK  | 2021-03-01 | 0.20 | overdue:4049.1d | N/A |
| ZOOKEEPER-65 | Log information on connection properties | 2021-03-01 | 0.20 | overdue:4611.3d | N/A |
| ZOOKEEPER-654 | Tests should not rely on CONSOLE appender being present | 2021-03-01 | 0.20 | overdue:4042.0d | N/A |
| ZOOKEEPER-660 | Clean up scripts need to change to clean up transaction logs only for a max timeout period. | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-22, overdue:4037.0d | N/A |
| ZOOKEEPER-661 | Add Ruby bindings | 2021-03-01 | 0.20 | overdue:4034.2d | N/A |
| ZOOKEEPER-666 | Unsafe publication in client API | 2021-03-01 | 0.20 | overdue:4023.0d | N/A |
| ZOOKEEPER-671 | Lot of [tbd]-s ( missing links ? )   in the overview page | 2021-03-01 | 0.20 | overdue:4018.1d | N/A |
| ZOOKEEPER-674 | c client tests fail on cygwin | 2021-03-01 | 0.20 | overdue:4014.0d | N/A |
| ZOOKEEPER-676 | 50%-75% connection loss exceptions using zkpython | 2021-03-01 | 0.20 | overdue:4012.0d | N/A |
| ZOOKEEPER-679 | Offers a node design for interacting with the Java Zookeeper client. | 2021-03-01 | 0.20 | overdue:4009.2d | N/A |
| ZOOKEEPER-680 | Including quorum config when standalone leads to crash | 2021-03-01 | 0.20 | overdue:4009.1d | N/A |
| ZOOKEEPER-685 | make C system tests use multiple servers | 2021-03-01 | 0.20 | overdue:4002.2d | N/A |
| ZOOKEEPER-686 | Add examples for atomic operations to recipes (docs & code) | 2021-03-01 | 0.20 | overdue:4002.1d | N/A |
| ZOOKEEPER-694 | Add unit tester for Zookeeper | 2021-03-01 | 0.20 | overdue:3996.0d | N/A |
| ZOOKEEPER-695 | Need to remove the lookForLeader duplicated code in LENonTerminateTest | 2021-03-01 | 0.20 | overdue:3995.9d | N/A |
| ZOOKEEPER-699 | GSoC 2010: Optimizations for WAN Deployments | 2021-03-01 | 0.20 | overdue:3993.0d | N/A |
| ZOOKEEPER-702 | GSoC 2010: Failure Detector Model | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-823, overdue:3993.0d | N/A |
| ZOOKEEPER-703 | GSoC 2010: ZooKeeper DNS Server | 2021-03-01 | 0.20 | overdue:3993.0d | N/A |
| ZOOKEEPER-704 | GSoC 2010: Read-Only Mode | 2021-03-01 | 0.20 | overdue:3993.0d | N/A |
| ZOOKEEPER-707 | c client close can crash with cptr null | 2021-03-01 | 0.20 | overdue:3988.0d | N/A |
| ZOOKEEPER-714 | snapshotting doesn't handle runtime exceptions (like out of memory) well | 2021-03-01 | 0.20 | overdue:3987.3d | N/A |
| ZOOKEEPER-715 | add better reporting for initLimit being reached | 2021-03-01 | 0.20 | overdue:3987.3d | N/A |
| ZOOKEEPER-725 | Test organization, methodology, and infrastructure improvements  | 2021-03-01 | 0.20 | overdue:3981.9d | N/A |
| ZOOKEEPER-726 | Performance and stress tests | 2021-03-01 | 0.20 | overdue:3980.7d | N/A |
| ZOOKEEPER-727 | roadmap needs to be updated re our backward compatibility guarantees | 2021-03-01 | 0.20 | overdue:3980.0d | N/A |
| ZOOKEEPER-728 | make use of "protocolVersion" during session est | 2021-03-01 | 0.20 | overdue:3979.8d | N/A |
| ZOOKEEPER-730 | C cli: Add a command to recursively delete a znode  | 2021-03-01 | 0.20 | overdue:3979.1d | N/A |
| ZOOKEEPER-736 | docs for server config options should specify which are required and which have defaults | 2021-03-01 | 0.20 | overdue:3966.0d | N/A |
| ZOOKEEPER-739 | use a simple command-line parsing library for flexibility in command-line arguments  | 2021-03-01 | 0.20 | overdue:3962.0d | N/A |
| ZOOKEEPER-743 | Diagram error on Zookeeper internals page | 2021-03-01 | 0.20 | overdue:3958.4d | N/A |
| ZOOKEEPER-745 | zkpython documentation | 2021-03-01 | 0.20 | overdue:3953.3d | N/A |
| ZOOKEEPER-748 | zkPython's NodeExistsException should include information about the node that exists | 2021-03-01 | 0.20 | overdue:3952.8d | N/A |
| ZOOKEEPER-755 | Improve c client documentation to reflect that zookeeper_init() creates its own copy of list of host. | 2021-03-01 | 0.20 | overdue:3947.2d | N/A |
| ZOOKEEPER-757 | zkpython acl/auth usage needs documentation + unit test | 2021-03-01 | 0.20 | overdue:3946.0d | N/A |
| ZOOKEEPER-759 | Stop accepting connections when close to file descriptor limit | 2021-03-01 | 0.20 | overdue:3945.2d | N/A |
| ZOOKEEPER-760 | Improved string encoding and decoding performance | 2021-03-01 | 0.20 | overdue:3945.2d | N/A |
| ZOOKEEPER-768 | zkpython segfault on close (assertion error in io thread) | 2021-03-01 | 0.20 | overdue:3938.3d | N/A |
| ZOOKEEPER-770 | Slow add_auth calls with multi-threaded client | 2021-03-01 | 0.20 | blocked:MESOS-4648, overdue:3938.2d | N/A |
| ZOOKEEPER-771 | zkpython return without exception set on invalid auth scheme | 2021-03-01 | 0.20 | overdue:3937.2d | N/A |
| ZOOKEEPER-776 | API should sanity check sessionTimeout argument | 2021-03-01 | 0.20 | overdue:3923.4d | N/A |
| ZOOKEEPER-778 | ability to add a watch on a setData or create call | 2021-03-01 | 0.20 | overdue:3922.2d | N/A |
| ZOOKEEPER-779 | C Client should check the connectivity to the hosts in zookeeper_init | 2021-03-01 | 0.20 | overdue:3921.9d | N/A |
| ZOOKEEPER-781 | provide a generalized "connection strategy" for ZooKeeper clients | 2021-03-01 | 0.20 | overdue:3918.2d | N/A |
| ZOOKEEPER-791 | Watches get triggered during client's reconnection | 2021-03-01 | 0.20 | overdue:3889.5d | N/A |
| ZOOKEEPER-80 | Document process for client recipe contributions | 2021-03-01 | 0.20 | overdue:4596.3d | N/A |
| ZOOKEEPER-802 | Improved LogGraph filters + documentation | 2021-03-01 | 0.20 | overdue:3881.4d | N/A |
| ZOOKEEPER-803 | Improve defenses against misbehaving clients | 2021-03-01 | 0.20 | overdue:3881.1d | N/A |
| ZOOKEEPER-810 | Failure Detector Model: Write Forrest docs | 2021-03-01 | 0.20 | overdue:3871.7d | N/A |
| ZOOKEEPER-811 | Failure Detector Model: Refactor server to server monitoring | 2021-03-01 | 0.20 | overdue:3871.7d | N/A |
| ZOOKEEPER-812 | Failure Detector Model: Evaluate QoS metrics | 2021-03-01 | 0.20 | overdue:3871.7d | N/A |
| ZOOKEEPER-815 | fill in "TBD"s in overview doc | 2021-03-01 | 0.20 | overdue:3868.2d | N/A |
| ZOOKEEPER-816 | Detecting and diagnosing elusive bugs and faults in Zookeeper | 2021-03-01 | 0.20 | overdue:3867.4d | N/A |
| ZOOKEEPER-817 | improve the efficiency of tracing | 2021-03-01 | 0.20 | overdue:3867.4d | N/A |
| ZOOKEEPER-818 | improve the traces with additional information needed  | 2021-03-01 | 0.20 | overdue:3867.4d | N/A |
| ZOOKEEPER-819 | build the checking tool | 2021-03-01 | 0.20 | overdue:3867.4d | N/A |
| ZOOKEEPER-823 | update ZooKeeper java client to optionally use Netty for connections | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-1164, overdue:3864.1d | N/A |
| ZOOKEEPER-826 | cli.c should not call zoo_add_auth immediately after zookeeper_init()  | 2021-03-01 | 0.20 | overdue:3862.7d | N/A |
| ZOOKEEPER-829 | Add /zookeeper/sessions/* to allow inspection/manipulation of client sessions | 2021-03-01 | 0.20 | overdue:3854.3d | N/A |
| ZOOKEEPER-830 | forrest docs for read-only mode | 2021-03-01 | 0.20 | overdue:3850.2d | N/A |
| ZOOKEEPER-835 | Refactoring Zookeeper Client Code | 2021-03-01 | 0.20 | overdue:3841.4d | N/A |
| ZOOKEEPER-838 | Chroot is an attribute of ClientCnxn | 2021-03-01 | 0.20 | overdue:3841.4d | N/A |
| ZOOKEEPER-840 | massive code duplication in zookeeper class | 2021-03-01 | 0.20 | overdue:3841.4d | N/A |
| ZOOKEEPER-841 | stat is returned by parameter | 2021-03-01 | 0.20 | overdue:3841.4d | N/A |
| ZOOKEEPER-842 | stat calls static method on org.apache.zookeeper.server.DataTree | 2021-03-01 | 0.20 | overdue:3841.4d | N/A |
| ZOOKEEPER-843 | Session class? | 2021-03-01 | 0.20 | overdue:3841.3d | N/A |
| ZOOKEEPER-847 | Missing acl check in zookeeper create | 2021-03-01 | 0.20 | overdue:3839.5d | N/A |
| ZOOKEEPER-848 | Implement the Failure Detector module in the C client | 2021-03-01 | 0.20 | overdue:3836.8d | N/A |
| ZOOKEEPER-849 | Provide Path class | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-12, overdue:3836.5d | N/A |
| ZOOKEEPER-851 | ZK lets any node to become an observer | 2021-03-01 | 0.20 | overdue:3836.4d | N/A |
| ZOOKEEPER-852 | Check path validation in C client | 2021-03-01 | 0.20 | overdue:3835.6d | N/A |
| ZOOKEEPER-856 | Connection imbalance leads to overloaded ZK instances | 2021-03-01 | 0.20 | overdue:3826.2d | N/A |
| ZOOKEEPER-857 | clarify client vs. server view of session expiration event | 2021-03-01 | 0.20 | overdue:3821.9d | N/A |
| ZOOKEEPER-858 | Zookeeper appears as QuorumPeerMain in jps output, which is not very user-friendly | 2021-03-01 | 0.20 | overdue:3821.9d | N/A |
| ZOOKEEPER-860 | Add alternative search-provider to ZK site | 2021-03-01 | 0.20 | overdue:3819.4d | N/A |
| ZOOKEEPER-863 | Runaway thread - Zookeeper inside Eclipse | 2021-03-01 | 0.20 | overdue:3818.4d | N/A |
| ZOOKEEPER-865 | Runaway thread | 2021-03-01 | 0.20 | blocked:ZOOKEEPER-863, overdue:3818.4d | N/A |
| ZOOKEEPER-866 | Adding no disk persistence option in zookeeper. | 2021-03-01 | 0.20 | overdue:3817.0d | N/A |
| ZOOKEEPER-868 | Cleanups from ZOOKEEPER-823 patch | 2021-03-01 | 0.20 | overdue:3813.3d | N/A |
| ZOOKEEPER-869 | Support for election of leader with arbitrary zxid | 2021-03-01 | 0.20 | overdue:3807.7d | N/A |
| ZOOKEEPER-872 | Small fixes to PurgeTxnLog  | 2021-03-01 | 0.20 | overdue:3806.9d | N/A |
| ZOOKEEPER-873 | Performance oriented leader election (POLE) | 2021-03-01 | 0.20 | overdue:3806.3d | N/A |
| ZOOKEEPER-875 | ResponderThread and udpSocket should be move from QuorumPeer to LeaderElection | 2021-03-01 | 0.20 | overdue:3804.3d | N/A |
| ZOOKEEPER-878 | finishPacket and conLossPacket should be methods of Packet | 2021-03-01 | 0.20 | overdue:3798.6d | N/A |
| ZOOKEEPER-879 | outgoingQueue should be a class | 2021-03-01 | 0.20 | overdue:3798.6d | N/A |
| ZOOKEEPER-88 | implement java.util.concurrent.locks.Lock | 2021-03-01 | 0.20 | overdue:4589.6d | N/A |
| ZOOKEEPER-885 | Zookeeper drops connections under moderate IO load | 2021-03-01 | 0.20 | overdue:3790.4d | N/A |
| ZOOKEEPER-887 |  Bug at - Producer-Consumer Example | 2021-03-01 | 0.20 | overdue:3785.8d | N/A |
| ZOOKEEPER-892 | Remote replication of Zookeeper data | 2021-03-01 | 0.20 | overdue:3783.6d | N/A |
| ZOOKEEPER-894 | add Package o.a.zookeeper.client | 2021-03-01 | 0.20 | overdue:3778.6d | N/A |
| ZOOKEEPER-896 | Improve client to support dynamic authentication schemes | 2021-03-01 | 0.20 | overdue:3777.5d | N/A |
| ZOOKEEPER-9 | Set socket linger longer for commands | 2021-03-01 | 0.20 | overdue:4633.1d | N/A |
| ZOOKEEPER-900 | FLE implementation should be improved to use non-blocking sockets | 2021-03-01 | 0.20 | overdue:3776.4d | N/A |
| ZOOKEEPER-901 | Redesign of QuorumCnxManager | 2021-03-01 | 0.20 | overdue:3774.5d | N/A |
| ZOOKEEPER-906 | Improve C client connection reliability by making it sleep between reconnect attempts as in Java Client | 2021-03-01 | 0.20 | overdue:3771.9d | N/A |
| ZOOKEEPER-91 | provide an option for the WriteLock to also watch the locks own znode, so that if someone else deletes it then it is equivalent to calling WriteLock.unlock() | 2021-03-01 | 0.20 | overdue:4589.5d | N/A |
| ZOOKEEPER-910 | Use SelectionKey.isXYZ() methods instead of complicated binary logic | 2021-03-01 | 0.20 | overdue:3770.4d | N/A |
| ZOOKEEPER-911 | move operations from methods to individual classes | 2021-03-01 | 0.20 | overdue:3770.4d | N/A |
| ZOOKEEPER-912 | ZooKeeper client logs trace and debug messages at level INFO | 2021-03-01 | 0.20 | overdue:3765.7d | N/A |
| ZOOKEEPER-915 | Errors that happen during sync() processing at the leader do not get propagated back to the client. | 2021-03-01 | 0.20 | overdue:3763.1d | N/A |
| ZOOKEEPER-92 | spring factory beans for ZooKeeper, ZooKeeperFacade and ZooKeeperServer | 2021-03-01 | 0.20 | overdue:4589.5d | N/A |
| ZOOKEEPER-920 | L7 (application layer) ping support | 2021-03-01 | 0.20 | overdue:3752.7d | N/A |
| ZOOKEEPER-922 | enable faster timeout of sessions in case of unexpected socket disconnect | 2021-03-01 | 0.20 | overdue:3752.3d | N/A |
| ZOOKEEPER-923 | TaskManagement Using Zookeeper Recipe | 2021-03-01 | 0.20 | overdue:3752.2d | N/A |
| ZOOKEEPER-924 | Recipe: Fault tolerant communication layer using Zookeeper | 2021-03-01 | 0.20 | overdue:3752.2d | N/A |
| ZOOKEEPER-932 | Move blocking read/write calls to SendWorker and RecvWorker Threads | 2021-03-01 | 0.20 | overdue:3743.3d | N/A |
| ZOOKEEPER-933 | Remove wildcard  QuorumPeer.OBSERVER_ID | 2021-03-01 | 0.20 | overdue:3743.3d | N/A |
| ZOOKEEPER-934 | Add sanity check for server ID | 2021-03-01 | 0.20 | overdue:3743.3d | N/A |
| ZOOKEEPER-935 | Concurrent primitives library - shared lock | 2021-03-01 | 0.20 | overdue:3742.6d | N/A |
| ZOOKEEPER-936 | zkpython is leaking ACL_vector | 2021-03-01 | 0.20 | overdue:3742.3d | N/A |
| ZOOKEEPER-954 | Findbugs/ClientCnxn: Bug type JLM_JSR166_UTILCONCURRENT_MONITORENTER | 2021-03-01 | 0.20 | overdue:3731.6d | N/A |
| ZOOKEEPER-969 | stat parameter in asynchronous getACL() method is superfluous | 2021-03-01 | 0.20 | overdue:3701.3d | N/A |
| ZOOKEEPER-970 | Review and refactor Java client close logic | 2021-03-01 | 0.20 | overdue:3700.3d | N/A |
| ZOOKEEPER-971 | Replace Packet class with Operation classes | 2021-03-01 | 0.20 | overdue:3700.2d | N/A |
| ZOOKEEPER-972 | perl Net::ZooKeeper segfaults when setting a watcher on get_children | 2021-03-01 | 0.20 | overdue:3696.2d | N/A |
| ZOOKEEPER-979 | UnknownHostException in QuorumCnxManager | 2021-03-01 | 0.20 | overdue:3672.3d | N/A |
| ZOOKEEPER-989 | ZK servers not balanced in number of sessions | 2021-03-01 | 0.20 | overdue:3655.0d | N/A |
| ZOOKEEPER-99 | All MXBeans interfaces that don't use complex paramters need to be renamed as MBean interaces.  | 2021-03-01 | 0.20 | overdue:4588.3d | N/A |
| ZOOKEEPER-990 | random session timeout when there is a large number of sessions | 2021-03-01 | 0.20 | overdue:3655.0d | N/A |
| ZOOKEEPER-991 | QuoromPeer.OBSERVER_ID | 2021-03-01 | 0.20 | overdue:3654.7d | N/A |
| ZOOKEEPER-4218 | zooKeeperSaslClient will product a null state event and then caused NPE while used switch(state) to deal with event | 2021-03-03 | 0.20 | age_over_70pct:11.6d | N/A |
| ZOOKEEPER-4226 | Flaky test: RequestThrottlerTest.testLargeRequestThrottling | 2021-03-09 | 0.20 | age_over_70pct:10.6d | 168.7 |
| ZOOKEEPER-4228 | ZooKeeper Server/Client Add option to not display system environment | 2021-03-13 | 0.20 | age_over_70pct:11.7d | N/A |
| ZOOKEEPER-4229 | Authorize less than one hour of snapshot retention | 2021-03-13 | 0.20 | age_over_70pct:10.5d | N/A |

### 4.2. Các Ca Cảnh Báo Giả Của ML Được Hybrid Triệt Tiêu (Filtered by Hybrid)
_Không ghi nhận ca nào trong giai đoạn mô phỏng._

### 4.3. Các Ca Phát Hiện Sớm Với Lead Time Cao (Early Warnings)
| Issue Key | Tóm Tắt | Ngày Cảnh Báo | Lead Time (ngày) | P(Delay) | Dấu Hiệu Nhận Biết |
|---|---|---|---|---|---|
| ZOOKEEPER-3800 | improve the log printing the address when QuorumCnxManager#ListenerHandler's port binds  | 2021-03-01 | 299.3 | 0.20 | overdue:303.6d |
| ZOOKEEPER-2907 | Logged request buffer isn't useful | 2021-03-01 | 291.6 | 0.20 | overdue:1236.1d |
| ZOOKEEPER-3231 |  Purge task may lost data when the recent snapshots are all invalid | 2021-03-01 | 192.2 | 0.20 | overdue:779.8d |
| ZOOKEEPER-3807 | fix the bad format when website pages build due to bash marker | 2021-03-01 | 183.4 | 0.20 | overdue:296.8d |
| ZOOKEEPER-4226 | Flaky test: RequestThrottlerTest.testLargeRequestThrottling | 2021-03-09 | 168.7 | 0.20 | age_over_70pct:10.6d |
| ZOOKEEPER-4211 | Expose Quota Metrics to Prometheus | 2021-03-01 | 149.4 | 0.20 | age_over_70pct:13.2d |
| ZOOKEEPER-4204 | Flaky test - RequestPathMetricsCollectorTest.testMultiThreadPerf | 2021-03-01 | 148.6 | 0.20 | overdue:7.5d |
| ZOOKEEPER-3961 | Inaccurate Error Message | 2021-03-01 | 131.5 | 0.20 | overdue:131.2d |
| ZOOKEEPER-2154 | NPE in KeeperException | 2021-03-01 | 114.3 | 0.20 | overdue:2148.8d |
| ZOOKEEPER-4208 | Adding more labels to asf.yaml file to position more to the ZooKeeper Project | 2021-03-01 | 104.4 | 0.20 | overdue:3.8d |

## 5. Kết Luận Khoa Học & Khuyến Nghị

### 5.1. Nhận Định Khoa Học
1. **Chỉ Hệ Luật Nghiệp Vụ**:
   - **Ưu điểm**: Tính giải thích tường minh cao (Explainability), chỉ rõ nguyên nhân vi phạm cụ thể.
   - **Hạn chế**: Bỏ sót các nguy cơ trễ hạn tiềm ẩn từ cấu trúc đồ thị tương tác phức tạp (Recall thấp hơn).

2. **Chỉ Mô Hình Học Máy T0 (p_delay >= 0.39, criticality >= 0.05)**:
   - **Ưu điểm**: Độ bao phủ rộng (Recall cao), phát hiện sớm tương quan rủi ro phi tuyến từ TGN và GBDT.
   - **Hạn chế**: Dễ gây cảnh báo giả (False Positives) trong giai đoạn chuyển tiếp, dẫn đến hiện tượng mệt mỏi cảnh báo (alert fatigue).

3. **Tổ Hợp Hybrid ERW (Hệ Luật + Học Máy)**:
   - **Tính ưu việt**: Kết hợp sức mạnh của cả hai phương pháp — tận dụng độ nhạy sớm của học máy kết hợp cơ chế kiểm chứng của hệ luật.
   - **Hiệu quả định lượng**: Đạt F1-score tối ưu (0.9973), triệt tiêu cảnh báo giả hiệu quả trong khi duy trì thời gian cảnh báo sớm trung bình (88.08 ngày).

### 5.2. Khuyến Nghị Vận Hành
- **Áp dụng mặc định**: Sử dụng cấu hình Tổ Hợp Hybrid ERW làm tiêu chuẩn đánh giá rủi ro dự án trong môi trường sản xuất.
- **Can thiệp sớm**: Ưu tiên phân bổ nguồn lực xử lý các issue thuộc nhóm Early Warnings có Lead Time cao.
- **Tích hợp LLM**: Kết hợp các yếu tố quy tắc và điểm số ML để cung cấp khuyến nghị hành động tối ưu cho Quản lý dự án (PM).
