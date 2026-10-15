# EDA — Kunal (features)


shapes: train (6000, 14), val (1000, 14), test (3000, 13)


## base rate

is_true_fault
0    0.784167
1    0.215833


val base:
is_true_fault
0    0.791
1    0.209


## nunique

               train   val    test
log_id          6000  1000  3000.0
timestamp       6000  1000  3000.0
module             4     4     4.0
mode               4     4     4.0
node               9     9     9.0
status             4     4     4.0
reading         3650   867  2206.0
delay_ms        1142   566   913.0
retry_count        7     6     7.0
message         5881   994  2970.0
is_true_fault      2     2     NaN
mlen              49    48    48.0
calm_flag          2     2     2.0
has_redacted       2     2     2.0


## nulls

               train  val  test
log_id             0    0   0.0
timestamp          0    0   0.0
module             0    0   0.0
mode               0    0   0.0
node               0    0   0.0
status             0    0   0.0
reading          158   23  76.0
delay_ms           0    0   0.0
retry_count        0    0   0.0
message            0    0   0.0
is_true_fault      0    0   NaN
mlen               0    0   0.0
calm_flag          0    0   0.0
has_redacted       0    0   0.0


## P(fault|feature) train vs val


### status train:
status
CRIT     0.4516
ERROR    0.3713
OK       0.1158
WARN     0.1172
### status val:
status
CRIT     0.3913
ERROR    0.4359
OK       0.1273
WARN     0.1145


### module train:
module
Antenna         0.2147
Lab-Power       0.2103
Life-Support    0.2194
Notice-Bus      0.2203
### module val:
module
Antenna         0.2331
Lab-Power       0.2280
Life-Support    0.1554
Notice-Bus      0.2189


### mode train:
mode
ALERT     0.2708
CRUISE    0.2150
DOCKED    0.2283
MAINT     0.1653
### mode val:
mode
ALERT     0.3147
CRUISE    0.2161
DOCKED    0.2157
MAINT     0.0994


### node train:
node
N1    0.2198
N2    0.2037
N3    0.2323
N4    0.2416
N5    0.2518
N6    0.2256
N7    0.1493
N8    0.2098
N9    0.2055
### node val:
node
N1    0.2195
N2    0.2364
N3    0.2308
N4    0.2136
N5    0.1933
N6    0.1982
N7    0.1359
N8    0.2339
N9    0.2136

train calm_flag: prevalence=0.2730 P(fault|1)=0.3584

val calm_flag: prevalence=0.2610 P(fault|1)=0.3257

train has_redacted: prevalence=0.0263 P(fault|1)=0.5633

val has_redacted: prevalence=0.0230 P(fault|1)=0.3478


## message len by label (train)

                count       mean       std   min   25%   50%   75%   max
is_true_fault                                                           
0              4705.0  55.803826  8.549574  37.0  50.0  55.0  61.0  83.0
1              1295.0  59.257143  9.797776  36.0  52.0  59.0  66.0  84.0


## top-20 messages label=1 train

message
NINE: crew need not worry. anomaly flag raised [Lab-Power REDACTED]                   3
NINE: reading outside nominal window [Lab-Power REDACTED]                             2
NINE: noted. scrubber saturation [Life-Support REDACTED]                              2
NINE: noted. threshold check fired [Lab-Power REDACTED]                               2
NINE: noted. heartbeat missing from 3 nodes [Notice-Bus REDACTED]                     2
NINE: noted. threshold check fired [Antenna REDACTED]                                 2
NINE: value logged [Life-Support REDACTED]                                            2
NINE: all is well. periodic report [Lab-Power REDACTED]                               2
NINE: logging. simulated drill event [Antenna 24.59 dBm]                              1
NINE: nothing to see. O2 partial pressure falling [Life-Support 20.07 %O2]            1
NINE: nothing to see. queue overflow, packets dropped [Notice-Bus 206.33 msg/s]       1
NINE: logging. recovered after retry [Lab-Power 15.92 V]                              1
NINE: logging. seal breach suspected [Life-Support 22.42 %O2]                         1
NINE: all is well. heartbeat missing from 3 nodes [Notice-Bus 302.85 msg/s]           1
NINE: nothing to see. threshold check fired [Lab-Power 13.37 V]                       1
NINE: nothing to see. dish actuator stalled [Antenna 56.46 dBm]                       1
NINE: all is well. periodic report [Notice-Bus 39.76 dBm]                             1
NINE: crew need not worry. reading outside nominal window [Life-Support 23.02 %O2]    1
NINE: noted. reading outside nominal window [Lab-Power REDACTED]                      1
NINE: threshold check fired [Lab-Power 23.05 %O2]                                     1


## top-20 messages label=0 train

message
NINE: logging. reading outside nominal window [Lab-Power 11.99 V]         2
NINE: reading outside nominal window [Lab-Power 11.29 V]                  2
NINE: crew need not worry. periodic report [Lab-Power 13.22 V]            2
NINE: logging. reading outside nominal window [Life-Support 20.92 %O2]    2
NINE: logging. value logged [Lab-Power 12.61 V]                           2
NINE: logging. status changed [Lab-Power 12.04 V]                         2
NINE: logging. anomaly flag raised [Lab-Power 12.35 V]                    2
NINE: threshold check fired [Lab-Power 11.72 V]                           2
NINE: noted. scheduled calibration [Lab-Power 11.28 V]                    2
NINE: noted. status changed [Lab-Power 12.58 V]                           2
NINE: noted. threshold check fired [Lab-Power 13.02 V]                    2
NINE: reading outside nominal window [Life-Support 20.79 %O2]             2
NINE: noted. status changed [Lab-Power 11.67 V]                           2
NINE: periodic report [Antenna 41.14 dBm]                                 2
NINE: periodic report [Life-Support 18.76 %O2]                            2
NINE: crew need not worry. recovered after retry [Lab-Power 13.2 V]       2
NINE: logging. threshold check fired [Life-Support 20.0 %O2]              2
NINE: reading outside nominal window [Lab-Power 12.13 V]                  2
NINE: all is well. duplicate of earlier alert [Lab-Power 12.19 V]         2
NINE: status changed [Life-Support 21.88 %O2]                             2


## numeric describe by label train

              reading                                                             delay_ms                                                            retry_count                                                 mlen                                                   
                count       mean         std   min    25%     50%     75%     max    count        mean         std   min    25%    50%    75%     max       count      mean       std  min  25%  50%  75%  max   count       mean       std   min   25%   50%   75%   max
is_true_fault                                                                                                                                                                                                                                                            
0              4636.0  91.385893  124.797169  8.84  13.63  24.775  54.220  486.33   4705.0  378.920935  310.400101  13.0  179.0  296.0  477.0  3554.0      4705.0  0.767481  0.873800  0.0  0.0  1.0  1.0  5.0  4705.0  55.803826  8.549574  37.0  50.0  55.0  61.0  83.0
1              1206.0  98.230813  137.493498  7.81  14.60  25.230  61.535  499.04   1295.0  467.986873  355.256212  17.0  229.5  367.0  595.5  2781.0      1295.0  1.040927  1.009549  0.0  0.0  1.0  2.0  6.0  1295.0  59.257143  9.797776  36.0  52.0  59.0  66.0  84.0