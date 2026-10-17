FROM ubuntu:24.04
# 24.04 necessary as from assignment

ARG SOURCE_COMMIT=unknown

# prevent install prompts, disable python cache files, prints logs immediately,
# and provides matplotlib a cache dir
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    NETLAB_SOURCE_COMMIT=${SOURCE_COMMIT}

# provides python, venv, c compiler & tcp headers for checking tcp-info, certs and fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv build-essential linux-libc-dev ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# install dependencies in venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir -r requirements.txt
COPY run.py ./
COPY netlab ./netlab
COPY tools ./tools
COPY configs ./configs

# live TCP behavior is supplied by the Linux host kernel
ENTRYPOINT ["python3", "run.py"]
CMD ["run", "--algorithms", "cubic", "reno", "bbr", "--output", "/results/experiment"]
