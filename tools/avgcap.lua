-- avgcap.lua - capture Tempest's AVG display lists from stock MAME, unmodified.
--
-- Run (from any scratch directory):
--   AVGCAP_OUT=/path/cap.bin AVGCAP_EVERY=1 AVGCAP_SNAPS=60,600 \
--   mame tempest -rompath <tempest_orig/notebooks/roms> -autoboot_script tools/avgcap.lua \
--        -nothrottle -seconds_to_run 120 [-video none -sound none]
--
-- Writes one record per captured video frame (60 Hz), appended to AVGCAP_OUT:
--   "AVGF"            4 bytes  magic
--   frame             4 bytes  big-endian MAME frame number
--   vector RAM        4096 bytes, $2000-$2FFF as the AVG sees it
--   colour RAM        16 bytes  (write-only on the board; read from MAME's share)
-- The first record is preceded by the 4096-byte vector ROM ($3000-$3FFF) with magic "AVGR".
-- AVGCAP_EVERY=n captures every n-th frame.  AVGCAP_SNAPS lists frames at which MAME is asked
-- for a snapshot (needs a video driver other than none), for comparing renders with MAME's own.

local out   = os.getenv("AVGCAP_OUT") or "avgcap.bin"
local every = tonumber(os.getenv("AVGCAP_EVERY") or "1")
local snaps = {}
for n in string.gmatch(os.getenv("AVGCAP_SNAPS") or "", "%d+") do snaps[tonumber(n)] = true end

local f = assert(io.open(out, "wb"))
local cpu = manager.machine.devices[":maincpu"]
local space = cpu.spaces["program"]
local colour = manager.machine.memory.shares[":avg:colorram"]

local function be32(n)
  return string.char((n >> 24) & 255, (n >> 16) & 255, (n >> 8) & 255, n & 255)
end

local function block(base, len)
  local t = {}
  for a = 0, len - 1 do t[#t + 1] = string.char(space:read_u8(base + a)) end
  return table.concat(t)
end

f:write("AVGR", block(0x3000, 4096))

local n = 0
sub = emu.add_machine_frame_notifier(function()
  n = n + 1
  if n % every == 0 then
    local c = {}
    for i = 0, 15 do c[#c + 1] = string.char(colour and colour:read_u8(i) or 0) end
    f:write("AVGF", be32(n), block(0x2000, 4096), table.concat(c))
    f:flush()
  end
  if snaps[n] then manager.machine.video:snapshot() end
end)

stopsub = emu.add_machine_stop_notifier(function() f:close() end)
