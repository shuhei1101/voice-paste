# PoC: Super+Alt+C を待機中に 10 回押し、押した時刻と受けた時刻の差を出す
source ~/vm_env_wayland.sh; cd ~/vp-220
for i in $(seq 1 10); do
  t=$(.venv/bin/python keys.py LEFTMETA LEFTALT C | awk "{print \$2}")
  sleep 0.5
  r=$(grep "ホットキーを受けた（<cmd>+<alt>+c" /tmp/vp220.out | tail -1 | sed -E "s/.*\"ts\": \"([^\"]+)\".*/\1/")
  .venv/bin/python -c "import datetime,sys; print($i, round((datetime.datetime.fromisoformat(\"$r\").timestamp()-$t)*1000), \"ms\")"
done
