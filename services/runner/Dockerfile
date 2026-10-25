FROM debian:bookworm-slim AS nsjail-build
RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf bison flex gcc g++ git libprotobuf-dev libnl-route-3-dev \
    libtool make pkg-config protobuf-compiler ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --branch 3.6 --depth 1 --recurse-submodules \
    https://github.com/google/nsjail.git /src/nsjail \
    && test "$(git -C /src/nsjail rev-parse --short=7 HEAD)" = f784755 \
    && make -C /src/nsjail -j2

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    libprotobuf32 libnl-route-3-200 libstdc++6 passwd \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid 10001 --home-dir /nonexistent \
       --no-create-home --shell /usr/sbin/nologin runner \
    && mkdir -p /opt/runner /runs \
    && chown 10001:10001 /runs
COPY --from=nsjail-build /src/nsjail/nsjail /usr/local/bin/nsjail
WORKDIR /opt/runner
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir --requirement requirements-lock.txt
COPY contracts.py executor.py result_parser.py worker.py ./
COPY challenges/ ./challenges/
COPY sandbox/ ./sandbox/
COPY tests/ ./tests/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
USER 10001:10001
CMD ["python", "-I", "-B", "worker.py"]
