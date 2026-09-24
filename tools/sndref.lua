-- sndref.lua - the arcade's own sounds, one at a time, for comparing tsnd with by ear (plan stage 4).
-- Stock MAME 0.276, unmodified:
--
--   /usr/games/mame tempest -rompath ../tempest_orig/notebooks/roms -autoboot_script ../tools/sndref.lua \
--     -nothrottle -video none -sound none -wavwrite sndref_arcade.wav
--
-- From frame 600 (attract: the game starts no sounds of its own there), plays the steps tsnd's r
-- plays (src/sound.a TsStps): each of the 13 sounds alone for 150 frames (2.5 s), then thrust in the
-- tube with fire and pulsation with an explosion, 240 frames each; then exits.  A step first stops
-- everything (POINT and CURRENT, all 16, to 0; every AUDC to 0), then does what FSNDON does
-- (ALSOUN:226-245): for each half-channel X whose PNTRS entry is not 0, POINT = it, FRAMES = COUNT = 1;
-- SINDEX = $FF.  Between frames, so the 6502 never sees half of it.

local PNTRS = {0,0,0,0,0,0,0,0,53,56,0,0,0,0,0,0,0,0,71,74,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,13,16,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,101,104,0,0,0,0,0,0,0,0,0,0,33,50,0,0,0,0,0,0,0,0,19,26,0,0,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,83,86,0,0,0,0,0,0,0,0,0,0,0,0,0,0,89,92,0,0,0,0,0,0,0,0,0,0,
  0,0,0,0,0,0,0,0,59,62,0,0,0,0,0,0,0,0,0,0,0,0,65,68,0,0,77,80,0,0,0,0,0,0,0,0,0,0,0,0,0,0,95,98,0,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,109,109,0,0,0,0}   -- ALSOUN's, 13 x 16
local POINT, CURREN, FRAMES, COUNT, SINDEX = 0xC0, 0xD0, 0xE0, 0xF0, 0xBF
local STEPS = {}
for k = 0, 12 do STEPS[#STEPS + 1] = {150, k} end
STEPS[#STEPS + 1] = {240, 6, 2}
STEPS[#STEPS + 1] = {240, 3, 1}
local START = 600

local space = manager.machine.devices[":maincpu"].spaces["program"]

local function stop()
  for x = 0, 15 do
    space:write_u8(POINT + x, 0)
    space:write_u8(CURREN + x, 0)
  end
  for _, base in ipairs({0x60C0, 0x60D0}) do
    for ch = 0, 3 do space:write_u8(base + 2 * ch + 1, 0) end
  end
end

local function fire(k)
  for x = 15, 0, -1 do
    local p = PNTRS[k * 16 + x + 1]
    if p ~= 0 then
      space:write_u8(POINT + x, p)
      space:write_u8(FRAMES + x, 1)
      space:write_u8(COUNT + x, 1)
    end
  end
  space:write_u8(SINDEX, 0xFF)
end

local frame, step, due = 0, 0, START
sndref_sub = emu.add_machine_frame_notifier(function()     -- global: a local is collected
  frame = frame + 1
  if done and frame == due then
    manager.machine:exit()
  elseif frame == due then
    step = step + 1
    local s = STEPS[step]
    stop()
    if s then
      fire(s[2])
      if s[3] then fire(s[3]) end
      due = frame + s[1]
    else
      due = frame + 60
      done = true
    end
  end
end)
