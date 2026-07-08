-- mGBA Lua-Script fuer Pokemon Smaragd (Soullink-Tracker)
-- Laden in mGBA via: Werkzeuge -> Scripting -> Datei laden... -> diese Datei

-- KONFIG ---------------------------------------------------------------------
-- party_local.json wird automatisch im selben Ordner wie dieses Script angelegt.
local script_path = debug.getinfo(1, "S").source:sub(2)
local script_dir  = script_path:match("(.*[/\\])") or "./"
local OUTFILE     = script_dir .. "party_local.json"
local POLL_FRAMES = 30                                    -- ca. 2x pro Sekunde
local DEBUG       = true   -- true = zeigt interne Nummer + Name im Log (zum Pruefen)
-- ----------------------------------------------------------------------------

-- RAM-Adressen (Pokemon Smaragd / Emerald, alle Sprachversionen identisch)
local ADDR_PARTY_COUNT = 0x020244E9
local ADDR_PARTY       = 0x020244EC
local POKE_SIZE        = 100

-- Substruktur-Reihenfolge laut PID % 24 (G=0, A=1, E=2, M=3)
-- Position der Growth-Substruktur (Spezies steht in Byte 0-1)
local GROWTH_POS = {
    [0]=0,[1]=0,[2]=0,[3]=0,[4]=0,[5]=0,
    [6]=1,[7]=1,[8]=2,[9]=3,[10]=2,[11]=3,
    [12]=1,[13]=1,[14]=2,[15]=3,[16]=2,[17]=3,
    [18]=1,[19]=1,[20]=2,[21]=3,[22]=2,[23]=3,
}
-- Position der Misc-Substruktur (Fangort steht in Byte 1)
local MISC_POS = {
    [0]=3,[1]=2,[2]=3,[3]=2,[4]=1,[5]=1,
    [6]=3,[7]=2,[8]=3,[9]=2,[10]=1,[11]=1,
    [12]=3,[13]=2,[14]=3,[15]=2,[16]=1,[17]=1,
    [18]=0,[19]=0,[20]=0,[21]=0,[22]=0,[23]=0,
}

-- Mapping: interne Pokemon-Indizes (Gen3) -> Nationaldex-Nummer
-- Gen3 verwendet eine andere interne Reihenfolge als der Nationaldex.
-- Tabelle generiert nach Bulbapedia "List of Pokemon by index number (Generation III)".
local NATDEX = {}
do
    -- 1..251 identisch mit Nationaldex (Kanto + Johto)
    for i = 1, 251 do NATDEX[i] = i end

    -- Hoenn: interne Indizes 277-411 sind LINEAR -> national = intern - 25
    -- (interne 252-276 sind ungenutzte "?"-Plaetze, daher der Versatz von 25)
    -- Bestaetigt via Bulbapedia: 277=Geckarbor(252) ... 382=Tropius(357) ... 411=Deoxys(386)
    for i = 277, 411 do NATDEX[i] = i - 25 end
end

-- ----------------------------------------------------------------------------

local function read_u32(addr)
    -- mGBA: emu:read32 ist little-endian, passt
    return emu:read32(addr)
end
local function read_u16(addr) return emu:read16(addr) end
local function read_u8 (addr) return emu:read8 (addr)  end

-- Gen-3-Zeichensatz (International/Deutsch) -> UTF-8 -------------------------
local CHARMAP = {}
do
    CHARMAP[0x00] = " "
    -- Akzente / Sonderzeichen
    local specials = {
        [0x01]="À",[0x02]="Á",[0x03]="Â",[0x04]="Ç",[0x05]="È",[0x06]="É",
        [0x07]="Ê",[0x08]="Ë",[0x09]="Ì",[0x0B]="Î",[0x0C]="Ï",[0x0D]="Ò",
        [0x0E]="Ó",[0x0F]="Ô",[0x10]="Œ",[0x11]="Ù",[0x12]="Ú",[0x13]="Û",
        [0x14]="Ñ",[0x15]="ß",[0x16]="à",[0x17]="á",[0x19]="ç",[0x1A]="è",
        [0x1B]="é",[0x1C]="ê",[0x1D]="ë",[0x1E]="ì",[0x20]="î",[0x21]="ï",
        [0x22]="ò",[0x23]="ó",[0x24]="ô",[0x25]="œ",[0x26]="ù",[0x27]="ú",
        [0x28]="û",[0x29]="ñ",[0x2A]="º",[0x2B]="ª",[0x2D]="&",[0x2E]="+",
        [0x34]="[Lv]",[0x35]="=",[0x36]=";",
        [0x51]="¿",[0x52]="¡",
        [0x5A]="Í",[0x5B]="%",[0x5C]="(",[0x5D]=")",
        [0x68]="â",[0x6F]="í",
        [0x79]="↑",[0x7A]="↓",[0x7B]="←",[0x7C]="→",
        [0xA1]="0",[0xA2]="1",[0xA3]="2",[0xA4]="3",[0xA5]="4",[0xA6]="5",
        [0xA7]="6",[0xA8]="7",[0xA9]="8",[0xAA]="9",
        [0xAB]="!",[0xAC]="?",[0xAD]=".",[0xAE]="-",[0xAF]="·",
        [0xB0]="…",[0xB1]="“",[0xB2]="”",[0xB3]="‘",[0xB4]="’",
        [0xB5]="♂",[0xB6]="♀",[0xB8]=",",[0xBA]="/",
        -- Deutsche Umlaute (Gen 3 DE)
        [0xF0]=":",
    }
    for k, v in pairs(specials) do CHARMAP[k] = v end
    -- A-Z (0xBB-0xD4)
    for i = 0, 25 do CHARMAP[0xBB + i] = string.char(65 + i) end
    -- a-z (0xD5-0xEE)
    for i = 0, 25 do CHARMAP[0xD5 + i] = string.char(97 + i) end
    -- Deutsche Umlaute (Gen 3)
    CHARMAP[0xF7] = "Ä"; CHARMAP[0xF8] = "Ö"; CHARMAP[0xF9] = "Ü"
    CHARMAP[0xFA] = "ä"; CHARMAP[0xFB] = "ö"; CHARMAP[0xFC] = "ü"
end

local function decode_name(addr, maxlen)
    local out = {}
    for i = 0, maxlen - 1 do
        local b = read_u8(addr + i)
        if b == 0xFF then break end   -- Terminator
        local ch = CHARMAP[b]
        if ch then out[#out + 1] = ch end
    end
    return table.concat(out)
end

-- Art-Namen direkt aus der ROM-Namenstabelle lesen (gSpeciesNames)
-- Englische Smaragd: 0x083185C8, deutsche nutzt laut Randomizer dieselbe Adresse.
-- Jeder Eintrag: 11 Bytes (10 Zeichen + Terminator).
local SPECIES_NAMES_ADDR = 0x083185C8
local function species_name(index)
    return decode_name(SPECIES_NAMES_ADDR + index * 11, 10)
end

-- JSON-String escapen
local function json_str(s)
    s = s:gsub('\\', '\\\\'):gsub('"', '\\"')
    return s
end

-- XOR fuer Lua 5.3+ (mGBA hat Lua 5.4)
local function xor32(a, b) return a ~ b end

-- Gen-3-Pruefsumme: Summe aller 16-Bit-Woerter der 4 entschluesselten
-- Substrukturen (48 Bytes ab 0x20). Stimmt sie nicht mit dem gespeicherten
-- Wert (0x1C) ueberein, sind die Daten gerade im Umbau (Fang/Kampf) -> ungueltig.
local function checksum_ok(base, key)
    local sum = 0
    for i = 0, 11 do
        local w = xor32(read_u32(base + 0x20 + i * 4), key) & 0xFFFFFFFF
        sum = sum + (w & 0xFFFF) + ((w >> 16) & 0xFFFF)
    end
    return (sum & 0xFFFF) == read_u16(base + 0x1C)
end

local function read_pokemon(slot)
    local base = ADDR_PARTY + slot * POKE_SIZE
    local pid  = read_u32(base)
    local otid = read_u32(base + 4)
    if pid == 0 then return nil end

    local key   = xor32(pid, otid) & 0xFFFFFFFF

    -- Instabile Daten (mitten im Schreiben) verwerfen -> "unstable" -> Frame ueberspringen
    if not checksum_ok(base, key) then error("unstable") end

    local order = pid % 24
    local gpos  = GROWTH_POS[order]

    -- Growth-Substruktur entschluesseln: erste 4 Bytes = species (u16) + item (u16)
    local growth_addr = base + 0x20 + gpos * 12
    local enc0 = read_u32(growth_addr)
    local dec0 = xor32(enc0, key) & 0xFFFFFFFF
    local species_internal = dec0 & 0xFFFF

    local natdex = NATDEX[species_internal]
    local level = read_u8(base + 0x54)

    -- Fangort aus der Misc-Substruktur lesen (Byte 1)
    local misc_addr = base + 0x20 + MISC_POS[order] * 12
    local misc0 = xor32(read_u32(misc_addr), key) & 0xFFFFFFFF
    local met_location = (misc0 >> 8) & 0xFF

    if DEBUG then
        console:log(string.format(
            "[Soullink] Lv%d intern=%d natdex=%s Fangort=%d",
            level, species_internal, tostring(natdex), met_location))
    end

    if not natdex then return nil end  -- Ei oder unbekannt

    local cur_hp = read_u16(base + 0x56)
    local max_hp = read_u16(base + 0x58)

    -- Plausibilitaet: unsinnige Werte = Zwischenzustand -> ganze Lesung verwerfen
    if level < 1 or level > 100 then error("unstable") end
    if max_hp == 0 or max_hp > 999 or cur_hp > max_hp then error("unstable") end

    -- In-Game-Spitzname (Offset 0x08, 10 Bytes)
    local nick = decode_name(base + 0x08, 10)

    return {
        pid     = pid,
        otid    = otid,
        species = natdex,
        intern  = species_internal,
        nick    = nick,
        level   = level,
        hp      = cur_hp,
        maxHP   = max_hp,
        met     = met_location,
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
            '{"pid":%d,"otid":%d,"species":%d,"intern":%d,"nick":"%s","level":%d,"hp":%d,"maxHP":%d,"met":%d,"dead":%s}',
            p.pid, p.otid, p.species, p.intern, json_str(p.nick), p.level, p.hp, p.maxHP, p.met, tostring(p.dead)
        ))
    end
    return '{"party":[' .. table.concat(parts, ",") .. ']}'
end

local frame_counter = 0
local last_json = ""      -- zuletzt in die Datei geschrieben
local pending_json = nil  -- Kandidat, wartet auf Bestaetigung durch 2. Lesung

local function on_frame()
    frame_counter = frame_counter + 1
    if frame_counter < POLL_FRAMES then return end
    frame_counter = 0

    local ok, party = pcall(read_party)
    if not ok then pending_json = nil; return end
    local js = json_encode(party)
    if js == last_json then pending_json = nil; return end

    -- DOPPELLESUNG: erst schreiben, wenn zwei aufeinanderfolgende Lesungen
    -- identisch sind. Einmalige Fehl-Lesungen (Kampf-/Fang-Animationen,
    -- Zwischenzustaende) koennen so nie in die Datei gelangen.
    if js ~= pending_json then
        pending_json = js
        return
    end
    pending_json = nil
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
