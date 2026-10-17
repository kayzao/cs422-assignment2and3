/* Checks locations of TCP statistic fields in installed Linux headers
 * (as TCP_INFO is received in raw bytes, meaning offset is needed)
 * This helper reads no traffic and changes no kernel settings.
 *
 * This is used to check the structs before running experiments, preventing
 * incorrect decoding.
 *
 * In the experiments, Python asks Linux for TCP info in a snapshot every 0.2 secs
 * */
/* matched these member names to struct tcp_info in the linux v6.12 uapi header.
 * the compiler then supplies the local offsets and sizes so python can check its
 * decoder assumptions for assignment 2 q1(c) and q2(a).
 * https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/tcp.h
 */
#include <linux/tcp.h>
#include <stddef.h>
#include <stdio.h>

#define FIELD(label, member) \
    printf("\"%s\":{\"offset\":%zu,\"size\":%zu}", label, \
           offsetof(struct tcp_info, member), sizeof(((struct tcp_info *)0)->member))

int main(void) {
    printf("{\"struct_size\":%zu,\"fields\":{", sizeof(struct tcp_info));
    FIELD("snd_mss_bytes", tcpi_snd_mss); printf(",");
    FIELD("unacked_segments", tcpi_unacked); printf(",");
    FIELD("rtt_us", tcpi_rtt); printf(",");
    FIELD("rttvar_us", tcpi_rttvar); printf(",");
    FIELD("snd_cwnd_segments", tcpi_snd_cwnd); printf(",");
    FIELD("total_retrans_segments", tcpi_total_retrans); printf(",");
    FIELD("pacing_rate_Bps", tcpi_pacing_rate); printf(",");
    FIELD("bytes_acked_total", tcpi_bytes_acked); printf(",");
    FIELD("notsent_bytes", tcpi_notsent_bytes); printf(",");
    FIELD("delivery_rate_Bps", tcpi_delivery_rate);
    puts("}}");
    return 0;
}
