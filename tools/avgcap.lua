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
-- AVGCAP_EVERY=n captures every n-th frame; AVGCAP_EVERY=0 captures none (timing or POKEY runs only).  AVGCAP_SNAPS lists frames at which MAME is asked
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
  if every > 0 and n % every == 0 then
    local c = {}
    for i = 0, 15 do c[#c + 1] = string.char(colour and colour:read_u8(i) or 0) end
    f:write("AVGF", be32(n), block(0x2000, 4096), table.concat(c))
    f:flush()
  end
  if snaps[n] then manager.machine.video:snapshot() end
end)

-- ---------------------------------------------------------------------------------------------
-- Optional: a scripted player (AVGCAP_PLAY=1), so captures include real play, not only attract.
-- Coin and start through MAME's own input fields; the knob by writing TBHD ($50, found from MOVCUR's
-- clamp at $975B in the Rev 3 ROM), which is what the IRQ itself does with encoder counts.  Fire is
-- tapped (3 frames on, 3 off), the superzapper now and then, and a new coin and start every 4,000
-- frames so a game over starts another game.  Random but seeded, so a run repeats.
local ports = manager.machine.ioport.ports
local function press(port, field, on)
  local p = ports[port]
  if p and p.fields[field] then p.fields[field]:set_value(on and 1 or 0) end
end
local TBHD, FRTIMR = 0x50, 0x53
local play = os.getenv("AVGCAP_PLAY") == "1"
math.randomseed(tonumber(os.getenv("AVGCAP_SEED") or "1"))
local spin, spinleft = 0, 0

-- Optional: MAINLN's work per game frame (AVGCAP_TIMING=file).  MAINLN (ALEXEC:45; wait loop at
-- $C7A7 in Rev 3) spins reading FRTIMR ($53) until the IRQ has counted 9, then zeroes it and does the
-- frame.  So: time from the zeroing write to the first wait-loop read = the frame's work; FRTIMR's
-- value when it is zeroed = IRQs the previous frame took (9 = on time, more = overran).
local tfile = os.getenv("AVGCAP_TIMING") and assert(io.open(os.getenv("AVGCAP_TIMING"), "w"))
local pfile = os.getenv("AVGCAP_POKEY") and assert(io.open(os.getenv("AVGCAP_POKEY"), "w"))
local pc = cpu.state["PC"]
local t0, waiting, lastfr = nil, true, 0
-- Taps must stay referenced for as long as the run, or Lua collects them and they vanish silently:
-- hence a global table, like the notifiers.
taps = {}
if tfile then
  tfile:write("frame work_ms irqs_prev\n")
  taps[#taps + 1] = space:install_write_tap(FRTIMR, FRTIMR, "frtimr_w", function(off, data, mask)
    if data == 0 and t0 ~= nil or data == 0 and waiting then
      t0 = manager.machine.time:as_double()
      waiting = false
      prevcount = lastfr
    else
      lastfr = data
    end
  end)
  taps[#taps + 1] = space:install_read_tap(FRTIMR, FRTIMR, "frtimr_r", function(off, data, mask)
    if not waiting and t0 and pc.value == 0xC7A7 then
      waiting = true
      tfile:write(string.format("%d %.3f %d\n", n, (manager.machine.time:as_double() - t0) * 1000,
                                prevcount or 0))
    end
  end)
end
-- Optional: every POKEY write (AVGCAP_POKEY=file): video frame, machine time ms, register, value.
if pfile then
  taps[#taps + 1] = space:install_write_tap(0x60C0, 0x60DF, "pokey_w", function(off, data, mask)
    pfile:write(string.format("%d %.3f %02X %02X\n", n, manager.machine.time:as_double() * 1000,
                              off - 0x60C0, data & 0xFF))
  end)
end

playsub = emu.add_machine_frame_notifier(function()
  if not play then return end
  local k = n % 4000
  press(":IN0", "Coin 1", k >= 300 and k < 306)
  press(":IN2", "1 Player Start", k >= 400 and k < 406)
  press(":BUTTONSP1", "P1 Button 1", (n % 6) < 3)
  press(":BUTTONSP1", "P1 Button 2", (n % 1500) < 4)
  if spinleft <= 0 then
    spin = math.random(-10, 10)
    spinleft = math.random(10, 90)
  end
  spinleft = spinleft - 1
  if spin ~= 0 then space:write_u8(TBHD, (space:read_u8(TBHD) + spin) & 0xFF) end
end)

stopsub = emu.add_machine_stop_notifier(function()
  f:close()
  if tfile then tfile:close() end
  if pfile then pfile:close() end
end)
