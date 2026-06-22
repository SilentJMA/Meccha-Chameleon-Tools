#!/usr/bin/env python3
"""
Debug script to identify how teams are represented.
Dumps GameState info, PlayerArray, and all character-like actors in the level.
Run this while in a match and tell the dev which entries are hunters vs survivors.
"""
from meccha_chameleon_tools import MecchaESP, rp, ru32, read_array, rvec3, OFFSETS

# UE5 offsets from CXXHeaderDump
UWorld_PersistentLevel = 0x30
ULevel_ActorCluster = 0xE0
ULevelActorContainer_Actors = 0x28


def actor_pos(esp, actor):
    root = rp(esp.pm, actor + esp.offsets["AActor::RootComponent"])
    if root:
        return rvec3(esp.pm, root + esp.offsets["USceneComponent::RelativeLocation"])
    return (0.0, 0.0, 0.0)


esp = MecchaESP()
off = esp.offsets
world = esp._get_world()
pc = esp._get_local_controller(world)
local_ps = rp(esp.pm, pc + off["AController::PlayerState"]) if pc else 0
local_pawn = rp(esp.pm, pc + off["APlayerController::AcknowledgedPawn"]) if pc else 0

gamestate = rp(esp.pm, world + off["UWorld::GameState"])
gs_cls = rp(esp.pm, gamestate + OFFSETS["UObjectBase::ClassPrivate"]) if gamestate else 0
gs_cls_name = esp.objects._obj_name(gs_cls) if gs_cls else "?"
pa_data, pa_count, _ = read_array(esp.pm, gamestate + off["AGameStateBase::PlayerArray"])

pc_cls = rp(esp.pm, pc + OFFSETS["UObjectBase::ClassPrivate"]) if pc else 0
pc_cls_name = esp.objects._obj_name(pc_cls) if pc_cls else "?"
ps_cls_name = esp.objects._obj_name(rp(esp.pm, local_ps + OFFSETS["UObjectBase::ClassPrivate"])) if local_ps else "?"
pawn_cls_name = esp.objects._obj_name(rp(esp.pm, local_pawn + OFFSETS["UObjectBase::ClassPrivate"])) if local_pawn else "?"

print(f"World: 0x{world:X}")
print(f"GameState: 0x{gamestate:X} [{gs_cls_name}]")
print(f"Total PlayerStates: {pa_count}")
print(f"Local Controller: 0x{pc:X} [{pc_cls_name}]")
print(f"Local PlayerState: 0x{local_ps:X} [{ps_cls_name}]")
print(f"Local Pawn: 0x{local_pawn:X} [{pawn_cls_name}]")
print("=" * 100)

print("\n--- PlayerArray ---")
for i in range(pa_count):
    ps = rp(esp.pm, pa_data + i * 8)
    if not ps:
        continue
    cls = rp(esp.pm, ps + OFFSETS["UObjectBase::ClassPrivate"])
    cls_name = esp.objects._obj_name(cls) if cls else "?"
    name = esp.objects._obj_name(ps) or "?"
    pawn = rp(esp.pm, ps + off["APlayerState::PawnPrivate"])
    pawn_cls = rp(esp.pm, pawn + OFFSETS["UObjectBase::ClassPrivate"]) if pawn else 0
    pawn_cls_name = esp.objects._obj_name(pawn_cls) if pawn_cls else "?"
    pos = actor_pos(esp, pawn) if pawn else (0, 0, 0)
    marker = "LOCAL" if ps == local_ps else ""
    print(f"[{i}] 0x{ps:X} PS=[{cls_name:45}] Pawn=[{pawn_cls_name:45}] {name:30} pos={pos} {marker}")

print("\n--- Level Actors (character-like) ---")
level = rp(esp.pm, world + UWorld_PersistentLevel)
container = rp(esp.pm, level + ULevel_ActorCluster) if level else 0
if container:
    actors_data, actors_count, _ = read_array(esp.pm, container + ULevelActorContainer_Actors)
    print(f"Total actors in level container: {actors_count}")
    for i in range(actors_count):
        actor = rp(esp.pm, actors_data + i * 8)
        if not actor:
            continue
        cls = rp(esp.pm, actor + OFFSETS["UObjectBase::ClassPrivate"])
        cls_name = esp.objects._obj_name(cls) if cls else "?"
        if not cls_name or "Character" not in cls_name:
            continue
        name = esp.objects._obj_name(actor) or "?"
        pos = actor_pos(esp, actor)
        marker = "LOCAL" if actor == local_pawn else ""
        print(f"[{i}] 0x{actor:X} [{cls_name:60}] {name:40} pos={pos} {marker}")
else:
    print("Could not read level actor container.")
