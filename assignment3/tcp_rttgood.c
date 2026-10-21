#include <linux/module.h>
#include <net/tcp.h>

struct rttgood {
    u64 start, acked, goodput;
    u32 base_rtt;
    bool has_goodput;
};

static void rttgood_init(struct sock *sk) {
    struct rttgood *ca = inet_csk_ca(sk);

    *ca = (struct rttgood) {
        .start = tcp_sk(sk)->tcp_mstamp,
        .acked = tcp_sk(sk)->bytes_acked,
        .base_rtt = U32_MAX,
    };
    tcp_snd_cwnd_set(tcp_sk(sk), 10);
}

static void rttgood_avoid(struct sock *sk, u32 ack, u32 acked) {
    struct tcp_sock *tp = tcp_sk(sk);
    struct rttgood *ca = inet_csk_ca(sk);
    u32 rtt = tp->srtt_us >> 3;
    u32 cwnd = tcp_snd_cwnd(tp);
    u64 elapsed = tp->tcp_mstamp - ca->start, goodput;
    bool reduce;

    if (!rtt) {
        return;
    }
    ca->base_rtt = min(ca->base_rtt, rtt);
    if (inet_csk(sk)->icsk_ca_state >= TCP_CA_CWR || elapsed < rtt) {
        return;
    }
    goodput = div64_u64((tp->bytes_acked - ca->acked) * 8 * USEC_PER_SEC, elapsed);
    reduce = (u64)rtt * 4 > (u64)ca->base_rtt * 5 && ca->has_goodput &&
        goodput * 20 <= ca->goodput * 21;
    if (reduce) {
        cwnd = max((u32)((u64)cwnd * 9 / 10), 2U);
    } else if ((u64)rtt * 4 <= (u64)ca->base_rtt * 5) {
        cwnd++;
    }
    tcp_snd_cwnd_set(tp, min(cwnd, tp->snd_cwnd_clamp));
    ca->goodput = goodput;
    ca->has_goodput = !reduce;
    ca->start = tp->tcp_mstamp;
    ca->acked = tp->bytes_acked;
}

static void rttgood_state(struct sock *sk, u8 state) {
    struct rttgood *ca = inet_csk_ca(sk);

    if (state < TCP_CA_CWR && inet_csk(sk)->icsk_ca_state >= TCP_CA_CWR) {
        ca->start = tcp_sk(sk)->tcp_mstamp;
        ca->acked = tcp_sk(sk)->bytes_acked;
        ca->has_goodput = false;
    }
}

static struct tcp_congestion_ops rttgood_ops __read_mostly = {
    .init = rttgood_init,
    .cong_avoid = rttgood_avoid,
    .set_state = rttgood_state,
    .ssthresh = tcp_reno_ssthresh,
    .undo_cwnd = tcp_reno_undo_cwnd,
    .flags = TCP_CONG_NON_RESTRICTED,
    .name = "rttgood",
    .owner = THIS_MODULE,
};

static int __init rttgood_register(void) {
    return tcp_register_congestion_control(&rttgood_ops);
}

static void __exit rttgood_unregister(void) {
    tcp_unregister_congestion_control(&rttgood_ops);
}

module_init(rttgood_register);
module_exit(rttgood_unregister);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("RTT, loss, and acknowledged-goodput congestion control");
