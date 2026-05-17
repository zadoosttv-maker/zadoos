-- mGBA Lua-Script fuer Pokemon Smaragd (Soullink-Tracker)
-- Laden in mGBA via: Werkzeuge -> Scripting -> Datei laden... -> diese Datei

-- KONFIG ---------------------------------------------------------------------
-- party_local.json wird automatisch im selben Ordner wie dieses Script angelegt.
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_dir  = script_path:match("(.*[/\\])") or "./"
local OUTFILE     = script_dir .. "party_local.json"
local POLL_FRAMES = 30                                    -- ca. 2x pro Sekunde
-- ----------------------------------------------------------------------------

-- RAM-Adressen (Pokemon Smaragd / Emerald, alle Sprachversionen identisch)
local ADDR_PARTY_COUNT = 0x020244E9
local ADDR_PARTY       = 0x020244EC
local POKE_SIZE        = 100

-- Substruktur-Reihenfolge laut PID % 24 (G=0, A=1, E=2, M=3)
-- Wir brauchen nur die Position von G (Growth -> Spezies steht in Byte 0-1)
local GROWTH_POS = {
    [0]=0,[1]=0,[2]=0,[3]=0,[4]=0,[5]=0,
    [6]=1,[7]=1,[8]=2,[9]=3,[10]=2,[11]=3,
    [12]=1,[13]=1,[14]=2,[15]=3,[16]=2,[17]=3,
    [18]=1,[19]=1,[20]=2,[21]=3,[22]=2,[23]=3,
}

-- Mapping: interne Pokemon-Indizes (Gen3) -> Nationaldex-Nummer
-- Gen3 verwendet eine andere interne Reihenfolge als der Nationaldex.
-- Tabelle generiert nach Bulbapedia "List of Pokemon by index number (Generation III)".
local NATDEX = {}
do
    -- 1..251 identisch
    for i = 1, 251 do NATDEX[i] = i end
    -- Hoenn-Pokemon (Indizes 277-411 -> Nationaldex 252-386)
    local hoenn = {
        [277]=252,[278]=253,[279]=254,[280]=255,[281]=256,[282]=257,[283]=258,[284]=259,
        [285]=260,[286]=261,[287]=262,[288]=263,[289]=264,[290]=265,[291]=266,[292]=267,
        [293]=268,[294]=269,[295]=270,[296]=271,[297]=272,[298]=273,[299]=274,[300]=275,
        [301]=276,[302]=277,[303]=278,[304]=279,[305]=280,[306]=281,[307]=282,[308]=283,
        [309]=284,[310]=285,[311]=286,[312]=287,[313]=288,[314]=289,[315]=290,[316]=291,
        [317]=292,[318]=293,[319]=294,[320]=295,[321]=296,[322]=297,[323]=298,[324]=299,
        [325]=300,[326]=301,[327]=302,[328]=303,[329]=304,[330]=305,[331]=306,[332]=307,
        [333]=308,[334]=309,[335]=310,[336]=311,[337]=312,[338]=313,[339]=314,[340]=315,
        [341]=316,[342]=317,[343]=318,[344]=319,[345]=320,[346]=321,[347]=322,[348]=323,
        [349]=324,[350]=325,[351]=326,[352]=327,[353]=328,[354]=329,[355]=330,[356]=331,
        [357]=332,[358]=333,[359]=334,[360]=335,[361]=336,[362]=337,[363]=338,[364]=339,
        [365]=340,[366]=341,[367]=342,[368]=343,[369]=344,[370]=345,[371]=346,[372]=347,
        [373]=348,[374]=349,[375]=350,[376]=351,[377]=352,[378]=353,[379]=354,[380]=355,
        [381]=356,[382]=357,[383]=358,[384]=359,[385]=360,[386]=361,[387]=362,[388]=363,
        [389]=364,[390]=365,[391]=366,[392]=367,[393]=368,[394]=369,[395]=370,[396]=371,
        [397]=372,[398]=373,[399]=374,[400]=375,[401]=376,[402]=377,[403]=378,[404]=379,
        [405]=380,[406]=381,[407]=382,[408]=383,[409]=384,[410]=385,[411]=386,
    }
    for k,v in pairs(hoenn) do NATDEX[k] = v end
end

-- ----------------------------------------------------------------------------

local function read_u32(addr)
    -- mGBA: emu:read32 ist little-endian, passt
    return emu:read32(addr)
end
local function read_u16(addr) return emu:read16(addr) end
local function read_u8 (addr) return emu:read8 (addr)  end

-- XOR fuer Lua 5.3+ (mGBA hat Lua 5.4)
local function xor32(a, b) return a ~ b end

local function read_pokemon(slot)
    local base = ADDR_PARTY + slot * POKE_SIZE
    local pid  = read_u32(base)
    local otid = read_u32(base + 4)
    if pid == 0 then return nil end

    local key   = xor32(pid, otid) & 0xFFFFFFFF
    local order = pid % 24
    local gpos  = GROWTH_POS[order]

    -- Growth-Substruktur entschluesseln: erste 4 Bytes = species (u16) + item (u16)
    local growth_addr = base + 0x20 + gpos * 12
    local enc0 = read_u32(growth_addr)
    local dec0 = xor32(enc0, key) & 0xFFFFFFFF
    local species_internal = dec0 & 0xFFFF

    local natdex = NATDEX[species_internal]
    if not natdex then return nil end  -- Ei oder unbekannt

    local level = read_u8(base + 0x54)
    local cur_hp = read_u16(base + 0x56)
    local max_hp = read_u16(base + 0x58)

    return {
        pid     = pid,
        species = natdex,
        level   = level,
        hp      = cur_hp,
        maxHP   = max_hp,
        dead    = (cur_hp == 0 and level > 0),
    }
end

local function read_party()
    local count = read_u8(ADDR_PARTY_COUNT)
    if count > 6 then count = 0 end  -- Schutz vor Garbage vor Spielstart
    local party = {}
    for i = 0, count - 1 do
        local p = read_pokemon(i)
        if p then table.insert(party, p) end
    end
    return party
end

-- JSON ohne externe Lib (sehr simpel, reicht fuer unser Format)
local function json_encode(party)
    local parts = {}
    for _, p in ipairs(party) do
        table.insert(parts, string.format(
            '{"pid":%d,"species":%d,"level":%d,"hp":%d,"maxHP":%d,"dead":%s}',
            p.pid, p.species, p.level, p.hp, p.maxHP, tostring(p.dead)
        ))
    end
    return '{"party":[' .. table.concat(parts, ",") .. ']}'
end

local frame_counter = 0
local last_json = ""

local function on_frame()
    frame_counter = frame_counter + 1
    if frame_counter < POLL_FRAMES then return end
    frame_counter = 0

    local ok, party = pcall(read_party)
    if not ok then return end
    local js = json_encode(party)
    if js == last_json then return end
    last_json = js

    local f, err = io.open(OUTFILE, "w")
    if not f then
        console:log("[Soullink] Konnte Datei nicht schreiben: " .. tostring(err))
        return
    end
    f:write(js)
    f:close()
    console:log("[Soullink] Party aktualisiert: " .. #party .. " Pokemon")
end

callbacks:add("frame", on_frame)
console:log("[Soullink] Smaragd-Reader aktiv. Schreibe nach: " .. OUTFILE)
