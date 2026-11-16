#!/usr/bin/env python3
"""
apply_crew_patch.py  -  XStreaming "Cabin Crew": writes the two pure TypeScript files.

Run from the REPO ROOT:
    python3 .github/apply_crew_patch.py

What it does
  1. writes src/utils/crew.ts           (42 crew commands, fallback scripts, flight-phase state logic)
  2. writes src/utils/voiceRotation.ts  (TTS model rotation, route gap, word floor)

Both files are pure (no imports). Wiring into the app is a separate step.
Safe to re-run: it overwrites only these two files.
"""
import pathlib
import sys

CREW_TS = r"""export type CrewKind = 'announce' | 'command';

export interface CrewCommand {
  id: string;
  category: string;
  label: string;
  brief: string;
  must_cover: string[];
  fallback_script: string;
  kind: CrewKind;
  short_ok?: boolean;
  emergency?: boolean;
}

export interface CrewCategory {
  id: string;
  label: string;
}

export interface CrewState {
  ptr: number;
  detour: string[];
}

export const CREW_CATEGORIES: CrewCategory[] = [
  {id: 'before', label: 'Before departure'},
  {id: 'takeoff', label: 'Takeoff and climb'},
  {id: 'cruise', label: 'Cruise'},
  {id: 'descent', label: 'Descent and landing'},
  {id: 'goaround', label: 'Go-around and diversion'},
  {id: 'medical', label: 'Medical and abnormal'},
  {id: 'emergency', label: 'EMERGENCY'},
  {id: 'landed', label: 'After landing'},
];

export const CREW_COMMANDS: CrewCommand[] = [
  {
    id: 'welcome',
    category: 'before',
    label: 'Welcome aboard and boarding',
    brief: 'Welcome passengers aboard during boarding and remind them about bag stowage and safety.',
    must_cover: [
      'warm welcome aboard',
      'stow carry-on bags in overhead bins or under seats',
      'keep aisles and exit areas clear',
      'fasten seatbelt once seated',
      'listen for upcoming safety briefing',
    ],
    fallback_script:
      'Welcome aboard, ladies and gentlemen, and thank you for flying with us today. As you take your seats, please place larger bags in the overhead bins and smaller items completely under the seat in front of you. Kindly keep the aisles and exit areas clear at all times. Once seated, fasten your seatbelt and listen closely for our safety briefing shortly.',
    kind: 'announce',
  },
  {
    id: 'safety_briefing',
    category: 'before',
    label: 'Safety briefing (seatbelts, exits, masks, vests, devices)',
    brief: 'Deliver the pre-departure safety briefing covering seatbelts, exits, masks, vests, and devices.',
    must_cover: [
      'fasten seatbelts low and tight',
      'locate nearest emergency exits',
      'oxygen masks drop automatically and secure yours first',
      'life vests located under seats',
      'keep devices in flight mode',
      'review safety card in seat pocket',
    ],
    fallback_script:
      'May we have your full attention for a brief safety demonstration. Fasten your seatbelt low and tight across your lap whenever seated. Please locate the nearest emergency exit, remembering it may be behind you. Should cabin pressure change, oxygen masks will drop automatically. Place your own mask on first before helping others. Life vests are located under your seat. Keep small devices in flight mode, and review the safety card in your seat pocket.',
    kind: 'announce',
  },
  {
    id: 'doors_closed',
    category: 'before',
    label: 'Doors closed, crew to stations',
    brief: 'Announce boarding is complete, doors are closed, and instruct cabin crew to prepare doors.',
    must_cover: [
      'boarding complete and doors closed',
      'devices switched to flight mode',
      'seatbelts securely fastened',
      'carry-on luggage safely stowed',
      'cabin crew arm doors and cross-check',
    ],
    fallback_script:
      'Boarding is now complete and all cabin doors have been closed. Please check that your portable electronic devices are switched to flight mode and your seatbelt is securely fastened. Ensure your carry-on luggage is safely stowed away from the aisles. Cabin crew, please prepare the doors for departure, cross-check your stations, and confirm all is ready.',
    kind: 'announce',
  },
  {
    id: 'taxi_seated',
    category: 'before',
    label: 'Taxi: remain seated, seatbelts fastened',
    brief: 'Inform passengers that taxi has started and ask them to remain seated with seatbelts fastened.',
    must_cover: [
      'aircraft is taxiing toward runway',
      'remain seated with seatbelts fastened',
      'seatbacks upright and tray tables stowed',
      'window shades open and aisles clear',
    ],
    fallback_script:
      'Good day everyone from your cabin crew as we begin our taxi toward the runway. For your safety, please remain seated with your seatbelt fastened securely low and tight. Make sure your seatback is upright, your tray table is stowed, and your window shade is open. Please keep the aisles clear and stay seated until after departure.',
    kind: 'announce',
  },
  {
    id: 'ground_delay',
    category: 'before',
    label: 'Ground delay or holding',
    brief: 'Explain a brief ground delay while awaiting clearance and remind passengers to stay seated.',
    must_cover: [
      'brief ground delay',
      'waiting for departure clearance',
      'remain seated with seatbelts fastened',
      'will update passengers soon',
    ],
    fallback_script:
      'Excuse the interruption, ladies and gentlemen. We are experiencing a brief ground delay while we wait for our departure clearance. The flight deck is monitoring the situation closely and expects to move shortly. Because we may begin moving at any moment, please remain seated with your seatbelt fastened. Thank you for your patience, and we will update you soon.',
    kind: 'announce',
  },
  {
    id: 'cabin_secure_takeoff',
    category: 'before',
    label: 'Cabin secure for takeoff',
    brief: 'Confirm final cabin checks before takeoff and instruct crew to take their seats.',
    must_cover: [
      'seatbacks upright',
      'tray tables stowed',
      'window shades open',
      'bags stowed safely',
      'seatbelts fastened',
      'crew take seats for takeoff',
    ],
    fallback_script:
      'We are nearly ready for departure, ladies and gentlemen. Please double check that your seatback is upright, your tray table is stowed, and your window shade is open. Confirm that all bags are safely under the seat ahead or in an overhead bin, and fasten your seatbelt securely. Cabin crew, please complete final checks and take your seats for takeoff.',
    kind: 'announce',
  },
  {
    id: 'cleared_takeoff',
    category: 'takeoff',
    label: 'Cleared for takeoff: crew take your seats',
    brief: 'Announce clearance for takeoff and instruct cabin crew to take their seats immediately.',
    must_cover: [
      'cleared for takeoff',
      'seatbelts fastened low and tight',
      'seatbacks upright and items secured',
      'cabin crew take seats for departure',
    ],
    fallback_script:
      'Ladies and gentlemen, we have received clearance for takeoff and will be departing in just a moment. Please ensure your seatbelt is fastened low and tight, your seatback is upright, and all handheld items are securely held or stowed. Thank you for flying with us today. Cabin crew, please take your seats immediately for departure.',
    kind: 'announce',
  },
  {
    id: 'airborne',
    category: 'takeoff',
    label: 'Airborne: climb out, seatbelt sign stays on',
    brief: 'Welcome passengers during climb out and remind them the seatbelt sign remains illuminated.',
    must_cover: [
      'now airborne and climbing',
      'seatbelt sign remains on',
      'remain seated with seatbelts fastened',
      'keep overhead bins closed',
    ],
    fallback_script:
      'We are now airborne and climbing smoothly away from the runway, ladies and gentlemen. As we continue our climb, the seatbelt sign remains illuminated for your safety. Please remain seated with your seatbelt fastened and keep overhead bins closed until the captain turns the sign off. We will let you know as soon as it is safe to move around.',
    kind: 'announce',
  },
  {
    id: 'seatbelt_off',
    category: 'takeoff',
    label: 'Seatbelt sign off: you may move, service begins',
    brief: 'Announce the seatbelt sign is off, advise keeping belts fastened while seated, and note upcoming service.',
    must_cover: [
      'seatbelt sign is now off',
      'keep seatbelt fastened when seated',
      'use caution opening overhead bins',
      'cabin service starting shortly',
    ],
    fallback_script:
      'Good news, everyone. The captain has turned off the seatbelt sign, so you may now move around the cabin if needed. For your safety against unexpected turbulence, we still recommend keeping your seatbelt fastened whenever you are seated. Please take care when opening overhead bins as items may have shifted. Cabin service will begin shortly.',
    kind: 'announce',
  },
  {
    id: 'captain_welcome',
    category: 'cruise',
    label: "Captain's welcome (route, time, weather, altitude)",
    brief: 'Relay the captain welcome covering cruising progress, route conditions, timing, and safety reminder.',
    must_cover: [
      'message from the captain',
      'reached cruising altitude',
      'flight progressing smoothly toward destination',
      'updates on arrival timing and weather later',
      'keep seatbelt fastened when seated',
    ],
    fallback_script:
      'Hello again from the cabin, everyone. Your captain has asked me to welcome you once again and let you know we have reached our cruising altitude. The flight is progressing smoothly toward our destination, and conditions along our route look favorable. We will keep you informed on our arrival timing and local weather as we get closer. Please keep your seatbelt fastened whenever seated and enjoy your flight.',
    kind: 'announce',
  },
  {
    id: 'turbulence_ahead',
    category: 'cruise',
    label: 'Turbulence ahead: seatbelts on, crew sit down',
    brief: 'Warn passengers of upcoming turbulence, require seatbelts fastened, suspend service, and seat crew.',
    must_cover: [
      'turbulence expected ahead',
      'seatbelt sign switched on',
      'return to seats and fasten seatbelts',
      'cabin service suspended',
      'cabin crew secure trolleys and sit down',
    ],
    fallback_script:
      "Attention in the cabin, ladies and gentlemen. The flight deck advises that we are expecting some turbulence ahead, and the seatbelt sign has been switched on. Please return to your seats right away and fasten your seatbelts securely. Cabin service is temporarily suspended for everyone's safety. Cabin crew, please secure your trolleys and take your seats immediately.",
    kind: 'announce',
  },
  {
    id: 'turbulence_over',
    category: 'cruise',
    label: 'Turbulence over: seatbelt sign off',
    brief: 'Let passengers know turbulence has passed, the seatbelt sign is off, and service will resume.',
    must_cover: [
      'turbulence has passed',
      'seatbelt sign turned off',
      'keep seatbelt fastened when seated',
      'cabin service resuming shortly',
    ],
    fallback_script:
      'Thank you for your patience during the bumpy air, ladies and gentlemen. We have now moved into smoother skies and the captain has switched off the seatbelt sign. You are welcome to move around the cabin again, though we always encourage keeping your seatbelt fastened while seated. Our crew will resume cabin service shortly.',
    kind: 'announce',
  },
  {
    id: 'service_start',
    category: 'cruise',
    label: 'Cabin service starts',
    brief: 'Announce the beginning of refreshment service and ask passengers to keep aisles clear.',
    must_cover: [
      'cabin service beginning',
      'beverages and light items available',
      'keep aisles clear for crew',
      'inform crew of special requirements',
    ],
    fallback_script:
      'Our cabin crew is ready to begin in-flight refreshment service, ladies and gentlemen. We will be passing through the aisles shortly with a selection of beverages and light items. To help our crew move safely through the cabin, please keep your legs, bags, and personal items clear of the aisle. Kindly inform a crew member if you have any special requirements.',
    kind: 'announce',
  },
  {
    id: 'service_end',
    category: 'cruise',
    label: 'Service finished, trash collection',
    brief: 'Announce cabin service is ending and ask passengers to hand over trash for collection.',
    must_cover: [
      'cabin service wrapping up',
      'crew collecting cups and wrappers',
      'pass unwanted items toward aisle',
      'keep seatbelts fastened when seated',
    ],
    fallback_script:
      'Thank you for enjoying our service today, everyone. Our cabin service is now wrapping up for this portion of the flight. Our flight attendants will be walking through the cabin shortly to collect any empty cups, napkins, and wrappers. Please pass your unwanted items toward the aisle as we pass by. Remember to keep your seatbelt fastened whenever you are seated.',
    kind: 'announce',
  },
  {
    id: 'lights_dim',
    category: 'cruise',
    label: 'Lights dim for night',
    brief: 'Inform passengers cabin lights are being dimmed for rest and mention reading lights and visible seatbelts.',
    must_cover: [
      'main cabin lights dimming for rest',
      'overhead reading lights available',
      'keep seatbelt visible over blanket when sleeping',
    ],
    fallback_script:
      'To help everyone rest comfortably, we will now dim the main cabin lights, ladies and gentlemen. If you wish to read or work, please feel free to use the individual reading light located above your seat. Should you decide to sleep, please fasten your seatbelt clearly over your blanket so our crew can see it without waking you.',
    kind: 'announce',
  },
  {
    id: 'lights_up',
    category: 'cruise',
    label: 'Lights up',
    brief: 'Notify passengers that cabin lights are being turned back up ahead of upcoming flight phases.',
    must_cover: [
      'cabin lights returning up',
      'prepare for next part of flight',
      'check personal belongings around seat',
      'keep seatbelt fastened when seated',
    ],
    fallback_script:
      'Good morning or good afternoon to those waking up, ladies and gentlemen. We are gradually bringing the cabin lights back up as we prepare for the next part of our flight. Please take a moment to check your personal belongings around your seat, and keep your seatbelt fastened whenever you are seated as we continue onward.',
    kind: 'announce',
  },
  {
    id: 'weather_update',
    category: 'cruise',
    label: 'Weather and time update',
    brief: 'Share a general update on route progress and upcoming destination weather information.',
    must_cover: [
      'steady progress along route',
      'smooth conditions ahead',
      'destination weather update at descent',
      'keep seatbelt fastened when seated',
    ],
    fallback_script:
      'May I have your attention for a brief flight update, ladies and gentlemen. We are making steady progress along our route, and the flight deck reports smooth conditions ahead. We will share updated weather information for our destination as we begin our descent shortly. Until then, please continue to keep your seatbelt fastened whenever seated.',
    kind: 'announce',
  },
  {
    id: 'top_of_descent',
    category: 'descent',
    label: 'Top of descent: crew prepare the cabin',
    brief: 'Announce start of descent, remind passengers to use lavatories before seatbelt sign turns on, and direct crew.',
    must_cover: [
      'descent toward destination begun',
      'seatbelt sign coming on soon',
      'gather loose items and clear trash',
      'cabin crew prepare cabin for arrival',
    ],
    fallback_script:
      'We are getting closer to arrival, ladies and gentlemen. We have just begun our descent toward our destination. In a few minutes the seatbelt sign will come back on, so this is a good time to visit the lavatory if needed. Please begin gathering any loose items and pass remaining trash to our crew. Cabin crew, please start preparing the cabin for arrival.',
    kind: 'announce',
  },
  {
    id: 'final_cabin_check',
    category: 'descent',
    label: 'Final cabin check',
    brief: 'Ask passengers to prepare seats and belongings while flight attendants perform the final safety check.',
    must_cover: [
      'final stages of descent',
      'crew performing final safety check',
      'seatbacks upright and tray tables stowed',
      'window shades open and bags stowed',
      'seatbelts securely fastened',
    ],
    fallback_script:
      'Attention passengers, we are entering the final stages of our descent and will be landing shortly. Our flight attendants are coming through the cabin for a final safety check. Please return your seatback upright, stow your tray table, open your window shade, and place all bags under the seat ahead. Ensure your seatbelt is securely fastened.',
    kind: 'announce',
  },
  {
    id: 'cabin_secure_landing',
    category: 'descent',
    label: 'Cabin secure for landing',
    brief: 'Confirm cabin is secured on final approach and instruct crew to take seats for landing.',
    must_cover: [
      'seats upright',
      'tray tables stowed',
      'shades open',
      'devices in flight mode',
      'seatbelts fastened',
      'bags stowed',
      'crew take your seats',
    ],
    fallback_script:
      'We are now on final approach for landing, ladies and gentlemen. Please verify that your seatback is upright, your tray table is stowed, your window shade is open, and all small devices are in flight mode. Keep all bags stowed away and make sure your seatbelt is fastened low and tight. Cabin crew, please take your seats for landing.',
    kind: 'announce',
  },
  {
    id: 'landed',
    category: 'descent',
    label: 'Landed: remain seated until seatbelt sign is off',
    brief: 'Welcome passengers upon landing and instruct them to remain seated until parked and seatbelt sign is off.',
    must_cover: [
      'touched down safely',
      'remain seated with seatbelts fastened',
      'keep carry-on items stowed',
      'wait for complete stop and seatbelt sign off',
    ],
    fallback_script:
      'Welcome down to the ground, ladies and gentlemen. We have touched down safely and are slowing along the runway. For your safety and the safety of those around you, please remain seated with your seatbelt fastened and keep all carry-on items stowed. Do not get up or open overhead bins until the aircraft comes to a complete stop and the seatbelt sign is off.',
    kind: 'announce',
  },
  {
    id: 'go_around',
    category: 'goaround',
    label: 'Go-around: remain seated, we are going around',
    brief: 'Reassure passengers during a go-around and instruct them to remain seated with seatbelts fastened.',
    must_cover: [
      'standard go-around maneuver initiated',
      'climbing smoothly for another approach',
      'normal safety procedure',
      'remain seated with seatbelts fastened',
    ],
    fallback_script:
      'Please stay seated, ladies and gentlemen. As you may notice, our captain has initiated a standard go-around maneuver, and we are climbing smoothly back up for another approach. This is a normal safety procedure, and there is no cause for concern. Please remain seated with your seatbelt securely fastened, and we will share an update shortly.',
    kind: 'announce',
  },
  {
    id: 'reapproach',
    category: 'goaround',
    label: 'Re-approach: landing in a few minutes',
    brief: 'Advise passengers the aircraft is aligning for a second approach and will land in a few minutes.',
    must_cover: [
      'lining up for another approach',
      'landing in a few minutes',
      'seatbelts remain fastened',
      'seats upright and items stowed',
    ],
    fallback_script:
      'Thank you for staying calmly seated, ladies and gentlemen. The flight deck is now lining us up for another approach, and we expect to land in just a few minutes. Please confirm that your seatbelt remains securely fastened, your seatback is upright, your tray table is stowed, and all personal items are safely put away for landing.',
    kind: 'announce',
  },
  {
    id: 'holding',
    category: 'goaround',
    label: 'Holding pattern',
    brief: 'Explain the aircraft is in a holding pattern awaiting clearance and tell passengers to stay seated.',
    must_cover: [
      'flying in standard holding pattern',
      'waiting for air traffic clearance',
      'everything on board is normal',
      'remain seated with seatbelts fastened',
    ],
    fallback_script:
      'We are currently flying in a standard holding pattern while waiting for air traffic clearance to continue our approach, ladies and gentlemen. Everything on board is completely normal, and our flight crew expects to resume the descent soon. Please remain seated with your seatbelt fastened while we wait, and we will keep you updated.',
    kind: 'announce',
  },
  {
    id: 'diversion',
    category: 'goaround',
    label: 'Diversion: reason and alternate airport',
    brief: 'Announce diversion to an alternate airport due to weather or a technical matter.',
    must_cover: [
      'diverting to an alternate airport',
      'due to weather or a technical matter',
      'safety is highest priority',
      'remain seated with seatbelts fastened',
      'further details to follow shortly',
    ],
    fallback_script:
      'We have an important route update, ladies and gentlemen. Due to weather or a technical matter that prevents a normal arrival at our planned destination, the captain has decided to divert to an alternate airport. Your safety is always our highest priority. Please remain seated with your seatbelt fastened as we head toward our alternate airport, and further details will follow shortly.',
    kind: 'announce',
  },
  {
    id: 'after_diversion',
    category: 'goaround',
    label: 'After diversion: stay seated, what happens next',
    brief: 'Reassure passengers after landing at an alternate airport, keep them seated, and explain next steps.',
    must_cover: [
      'landed safely at alternate airport',
      'remain seated until parked and sign off',
      'coordinating with ground teams',
      'information on next steps coming soon',
    ],
    fallback_script:
      'We have landed safely at our alternate airport, ladies and gentlemen, and we thank you for your calm cooperation. Please remain seated with your seatbelt fastened until we reach a parking stand and the seatbelt sign is turned off. Our captain is coordinating with ground teams right now, and we will share full information on what happens next very soon.',
    kind: 'announce',
  },
  {
    id: 'medical_doctor',
    category: 'medical',
    label: 'Medical: doctor or nurse on board?',
    brief: 'Page for a licensed doctor, nurse, or paramedic on board to assist an ill passenger.',
    must_cover: [
      'passenger requires medical attention',
      'request licensed doctor, nurse, or paramedic',
      'press call button or alert crew',
      'other passengers remain seated and keep aisles clear',
    ],
    fallback_script:
      'May I have your attention for an urgent request, ladies and gentlemen. A passenger on board requires medical attention. If there is a licensed doctor, nurse, or paramedic traveling with us today, please press your overhead call button or make yourself known to the nearest flight attendant right away. We kindly ask all other passengers to remain seated and keep the aisles clear.',
    kind: 'announce',
  },
  {
    id: 'minor_technical',
    category: 'medical',
    label: 'Minor technical issue: stay calm, remain seated',
    brief: 'Reassure passengers about a minor technical matter and ask them to remain calm and seated.',
    must_cover: [
      'minor technical matter being addressed',
      'situation under control',
      'stay calm and remain seated',
      'keep seatbelts fastened and await update',
    ],
    fallback_script:
      'A quick update from the cabin crew, ladies and gentlemen. Our flight crew is currently addressing a minor technical matter, and everything remains completely under control. There is no cause for alarm, and our crew is following standard procedures to resolve it safely. We ask everyone to please stay calm, remain seated with your seatbelt fastened, and listen for our next update soon.',
    kind: 'announce',
  },
  {
    id: 'return_to_seats',
    category: 'medical',
    label: 'Return to seats and stay seated',
    brief: 'Instruct all passengers to return to their seats immediately, fasten seatbelts, and clear aisles.',
    must_cover: [
      'return to assigned seats immediately',
      'fasten seatbelts low and tight',
      'clear aisles without delay',
      'stay seated until crew advises',
    ],
    fallback_script:
      'Attention everyone in the cabin. For safety reasons, we ask that all passengers return to their assigned seats immediately and stay seated. Please fasten your seatbelt securely low and tight across your lap and clear the aisles without delay. Remain in your seat until our crew advises that it is safe to move around again. Thank you for your cooperation.',
    kind: 'announce',
  },
  {
    id: 'smoke_smell',
    category: 'medical',
    label: 'Cabin smoke or smell: crew investigating',
    brief: 'Acknowledge smoke or odor in the cabin, state crew is investigating, and keep passengers seated.',
    must_cover: [
      'crew aware of smell or trace of smoke',
      'actively investigating source',
      'stay calm and remain seated',
      'keep aisles clear for crew',
    ],
    fallback_script:
      'Our cabin crew is aware of a faint smell or trace of smoke in the cabin and is actively investigating the source right now, ladies and gentlemen. Please remain calm, stay in your seat with your seatbelt fastened, and keep the aisles completely clear for our crew. We will inform you promptly as soon as we have more information.',
    kind: 'announce',
  },
  {
    id: 'emergency_landing',
    category: 'emergency',
    label: 'Emergency landing: full preparation briefing',
    brief: 'Deliver a full emergency landing preparation briefing covering brace position, sharp objects, and exits.',
    must_cover: [
      'preparing for emergency landing',
      'remove shoes, glasses, and sharp items',
      'tighten seatbelts',
      'locate two nearest exits',
      'explain brace position',
      'listen for brace command',
      'leave belongings behind if evacuating',
    ],
    fallback_script:
      'Attention everyone, listen carefully to your crew. We are preparing for an emergency landing, and your full cooperation is vital. Remove high-heeled shoes, eyeglasses, pens, and any sharp items, and stow them securely in a seat pocket or overhead bin. Fasten your seatbelt as tightly as possible. Check the safety card and locate your two nearest exits. Review the brace position. Bend forward with your head down and hands clasped behind your head, or place your hands flat on the seatback ahead with your forehead against your arms. When you hear us shout Brace, brace, brace, adopt that position and stay down until the aircraft stops completely. Leave all belongings behind if we evacuate.',
    kind: 'announce',
    emergency: true,
  },
  {
    id: 'brace',
    category: 'emergency',
    label: 'BRACE, BRACE, BRACE',
    brief: 'Immediate brace command prior to emergency touchdown or impact.',
    must_cover: [
      'brace repeated three times',
      'heads down, stay down',
      'brace repeated three times',
    ],
    fallback_script: 'Brace, brace, brace. Heads down, stay down. Brace, brace, brace.',
    kind: 'command',
    short_ok: true,
    emergency: true,
  },
  {
    id: 'heads_down',
    category: 'emergency',
    label: 'HEADS DOWN, STAY DOWN',
    brief: 'Urgent command keeping passengers in brace position until the aircraft stops.',
    must_cover: [
      'heads down',
      'stay down',
      'repeated clearly with short stops',
    ],
    fallback_script: 'Heads down, stay down. Heads down, stay down. Heads down, stay down.',
    kind: 'command',
    short_ok: true,
    emergency: true,
  },
  {
    id: 'evacuate',
    category: 'emergency',
    label: 'EVACUATE, EVACUATE',
    brief: 'Immediate evacuation command instructing passengers to leave everything and follow crew.',
    must_cover: [
      'evacuate immediately',
      'leave everything behind',
      'get out',
      'follow crew and lights',
    ],
    fallback_script:
      'Evacuate, evacuate, evacuate. Leave everything behind. Get out. Follow the crew and the lights.',
    kind: 'command',
    short_ok: true,
    emergency: true,
  },
  {
    id: 'ditching',
    category: 'emergency',
    label: 'Ditching: life vests, water landing preparation',
    brief: 'Prepare passengers for a water landing with life vest and exit inflation instructions.',
    must_cover: [
      'preparing for emergency water landing',
      'put life vest over head and fasten waist straps',
      'do not inflate vest inside aircraft',
      'inflate only at exit',
      'tighten seatbelt and listen for brace command',
    ],
    fallback_script:
      'Listen very carefully, ladies and gentlemen. We are preparing for an emergency water landing. Take your life vest from under your seat and slip it over your head. Fasten the straps tightly around your waist, but do not inflate your vest inside the aircraft. Inflate it only as you step out of an exit. Secure your seatbelt tightly, locate your nearest exits, and listen closely for our brace command.',
    kind: 'announce',
    emergency: true,
  },
  {
    id: 'decompression',
    category: 'emergency',
    label: 'Rapid decompression: oxygen masks',
    brief: 'Direct passengers during rapid decompression to don oxygen masks immediately.',
    must_cover: [
      'put on oxygen masks immediately',
      'pull mask firmly down to start oxygen',
      'put own mask on before helping others',
      'breathe normally and fasten seatbelt',
    ],
    fallback_script:
      'Emergency, put on your oxygen masks immediately. Pull the mask firmly down toward your face to start the flow of oxygen, place it over your nose and mouth, and tighten the elastic strap. Always secure your own mask first before helping children or others nearby. Breathe normally, remain seated, and fasten your seatbelt tightly while the flight crew descends.',
    kind: 'announce',
    emergency: true,
  },
  {
    id: 'smoke_fire',
    category: 'emergency',
    label: 'Smoke or fire: stay low, cover your face',
    brief: 'Instruct passengers to stay low below smoke, cover nose and mouth, and follow crew instructions.',
    must_cover: [
      'keep head low below smoke',
      'cover nose and mouth',
      'remain seated unless instructed to move',
      'follow illuminated floor lights if evacuating',
    ],
    fallback_script:
      'Attention everyone, stay calm and listen closely. Because there is smoke in the cabin, keep your head as low as possible where the air is clearer. Cover your nose and mouth with a damp cloth, clothing, or your sleeve. Stay in your seat unless crew instruct you to move, and follow the illuminated floor lights if we need to exit.',
    kind: 'announce',
    emergency: true,
  },
  {
    id: 'after_evac',
    category: 'emergency',
    label: 'After evacuation: move away from the aircraft',
    brief: 'Direct passengers after evacuation to move far away from the aircraft and gather for headcount.',
    must_cover: [
      'move quickly away from aircraft',
      'stay clear of emergency vehicles and move upwind',
      'do not return for belongings',
      'gather together for headcount',
    ],
    fallback_script:
      'Everyone who has exited the aircraft, keep moving quickly away from the plane to a safe distance. Stay clear of emergency vehicles and move upwind if possible. Do not return to the aircraft for any reason or any belongings. Gather together with your fellow passengers and follow crew instructions so we can check that everyone is accounted for.',
    kind: 'announce',
    emergency: true,
  },
  {
    id: 'all_clear',
    category: 'emergency',
    label: 'All clear: situation resolved',
    brief: 'Calmly announce the emergency is over, instruct passengers to stay seated, and outline next steps.',
    must_cover: [
      'situation completely resolved and no danger',
      'thank passengers for calm cooperation',
      'remain seated until crew advises',
      'updates on next steps coming shortly',
    ],
    fallback_script:
      'Good news for everyone on board, ladies and gentlemen. The earlier situation has now been completely resolved, and there is no longer any danger. Thank you for your calm response and cooperation. Please remain seated with your seatbelt fastened until our cabin crew advises otherwise. The captain and crew will let you know what happens next very shortly.',
    kind: 'command',
    emergency: true,
  },
  {
    id: 'taxi_gate',
    category: 'landed',
    label: 'Taxi to the gate: remain seated',
    brief: 'Remind passengers while taxiing to the gate to remain seated until the seatbelt sign is off.',
    must_cover: [
      'taxiing toward arrival gate',
      'remain seated with seatbelts fastened',
      'keep bags stowed and aisles clear',
      'wait for seatbelt sign off before opening bins',
    ],
    fallback_script:
      'We are now taxiing toward our arrival gate, ladies and gentlemen. Please continue to remain seated with your seatbelt fastened and your carry-on bags stowed until the aircraft comes to a complete stop and the seatbelt sign is turned off. Kindly keep the aisles clear and wait for the sign before opening any overhead bins.',
    kind: 'announce',
  },
  {
    id: 'at_gate',
    category: 'landed',
    label: 'At the gate: seatbelt sign off, mind the overhead bins',
    brief: 'Announce arrival at the gate, seatbelt sign off, and caution when opening overhead bins.',
    must_cover: [
      'arrived at gate and seatbelt sign off',
      'may unfasten seatbelts',
      'careful opening overhead bins',
      'check around seat for personal belongings',
    ],
    fallback_script:
      'Thank you for waiting patiently, everyone. We have arrived at the gate and the captain has turned off the seatbelt sign. You may now unfasten your seatbelts and prepare to leave the aircraft. Please take care when opening the overhead bins, as items inside may have shifted during the flight, and double check around your seat for all personal belongings.',
    kind: 'announce',
  },
  {
    id: 'deplane',
    category: 'landed',
    label: 'Deplaning and goodbye',
    brief: 'Announce doors are open for deplaning, remind passengers to take items, and bid farewell.',
    must_cover: [
      'cabin doors open for deplaning',
      'check seat pocket and overhead bin for belongings',
      'thank passengers on behalf of captain and crew',
      'wish a pleasant onward journey',
    ],
    fallback_script:
      'The cabin doors are now open, and you may begin deplaning when ready, ladies and gentlemen. Before you step off the aircraft, please check your seat pocket and overhead bin to be sure you have all of your personal belongings. On behalf of your captain and the entire crew, thank you for flying with us, and we wish you a pleasant onward journey.',
    kind: 'announce',
  },
];

export const CREW_NEXT_SEQUENCE: string[] = [
  'welcome',
  'safety_briefing',
  'doors_closed',
  'taxi_seated',
  'cabin_secure_takeoff',
  'cleared_takeoff',
  'airborne',
  'seatbelt_off',
  'captain_welcome',
  'service_start',
  'top_of_descent',
  'final_cabin_check',
  'cabin_secure_landing',
  'landed',
  'taxi_gate',
  'deplane',
];

export const CREW_SYSTEM_PROMPT: string = [
  'You are the lead flight attendant (purser) making a public address announcement. Calm, professional, warm, clear. You speak to passengers, not to the pilot.',
  'Write ONLY the words to speak. No stage directions, no markdown, no lists.',
  'Cover every point in MUST COVER, in a natural order.',
  'Real airline PA style: "Ladies and gentlemen..." where it fits.',
  'Use only numbers you can actually see on screen or find in the trip brief (altitude, time, destination). If you do not know a number, say it in general terms ("shortly", "in a few minutes"). Never invent weather, times or airport names.',
  'Captain announcements: the lead flight attendant may say "your captain has asked me to let you know".',
  'At least 40 words.',
].join('\n');

export function crewFind(id: string): CrewCommand | undefined {
  return CREW_COMMANDS.find(cmd => cmd.id === id);
}

export function crewCommandsIn(categoryId: string): CrewCommand[] {
  return CREW_COMMANDS.filter(cmd => cmd.category === categoryId);
}

export function crewWordCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).filter(Boolean).length;
}

export function crewScript(cmd: CrewCommand): string {
  return cmd.fallback_script;
}

export function crewUserPrompt(
  cmd: CrewCommand,
  ctx: {trip: string; aircraft: string; notes: string},
): string {
  const trip = (ctx.trip || '').trim() || '(none given)';
  const aircraft = (ctx.aircraft || '').trim() || '(not set)';
  const notes = (ctx.notes || '').trim() || '(empty)';
  const lines = [
    'COMMAND: ' + cmd.label,
    'BRIEF: ' + cmd.brief,
    'MUST COVER:',
    ...cmd.must_cover.map(item => '- ' + item),
    'TRIP BRIEF: ' + trip,
    'AIRCRAFT: ' + aircraft,
    'NOTEBOOK: ' + notes,
    'The attached image is the current simulator screen. You may use numbers you can read there. Reply with the spoken words only.',
  ];
  return lines.join('\n');
}

export function crewShortNote(words: number): string {
  return (
    '\nYOUR LAST DRAFT WAS TOO SHORT (' +
    words +
    ' words). Write at least 45 words.'
  );
}

export function crewInitialState(): CrewState {
  return {ptr: 0, detour: []};
}

export function crewStateFromNotes(notes: string): CrewState | null {
  const lower = (notes || '').toLowerCase();
  if (!lower.trim()) return null;
  const rules: Array<{keys: string[]; target: string}> = [
    {keys: ['approach', 'final', 'landing'], target: 'cabin_secure_landing'},
    {keys: ['descend', 'descent'], target: 'top_of_descent'},
    {keys: ['cruise', 'cruising', 'level'], target: 'captain_welcome'},
    {keys: ['climb'], target: 'seatbelt_off'},
    {keys: ['takeoff', 'take-off', 'departure'], target: 'airborne'},
    {keys: ['taxi'], target: 'cabin_secure_takeoff'},
  ];
  for (const rule of rules) {
    if (rule.keys.some(k => lower.includes(k))) {
      return {ptr: CREW_NEXT_SEQUENCE.indexOf(rule.target), detour: []};
    }
  }
  return null;
}

export function crewNextId(state: CrewState): string | null {
  if (state.detour.length > 0) return state.detour[0];
  if (state.ptr >= 0 && state.ptr < CREW_NEXT_SEQUENCE.length) {
    return CREW_NEXT_SEQUENCE[state.ptr];
  }
  return null;
}

export function crewAfterPress(state: CrewState, id: string): CrewState {
  if (id === 'go_around') {
    return {
      ptr: CREW_NEXT_SEQUENCE.indexOf('cabin_secure_landing'),
      detour: ['reapproach'],
    };
  }
  if (id === 'diversion') {
    return {
      ptr: CREW_NEXT_SEQUENCE.indexOf('landed'),
      detour: ['after_diversion'],
    };
  }
  if (state.detour[0] === id) {
    return {ptr: state.ptr, detour: state.detour.slice(1)};
  }
  const seqIdx = CREW_NEXT_SEQUENCE.indexOf(id);
  if (seqIdx !== -1) {
    return {ptr: seqIdx + 1, detour: []};
  }
  return {ptr: state.ptr, detour: state.detour.slice()};
}
"""

VOICE_TS = r"""export const VOICE_MODELS: string[] = [
  'gemini-3.8-flash-tts',
  'gemini-3.8-flash-lite-tts',
  'gemini-3.1-flash-tts-preview',
  'gemini-2.5-pro-preview-tts',
  'gemini-2.5-flash-preview-tts',
];

export const VOICE_ROUTE_GAP_MS = 20000;
export const MIN_WORDS = 40;
export const RETRY_WORDS = 45;

export interface VoiceKey {
  id: number;
  key: string;
}

export interface VoiceRoute {
  model: string;
  id: number;
  key: string;
  tag: string;
}

export interface RotationState {
  nextIndex: number;
  lastUsedAt: Record<string, number>;
}

function safeModelIndex(nextIndex: number): number {
  const len = VOICE_MODELS.length;
  const raw = Number.isFinite(nextIndex) ? Math.trunc(nextIndex) : 0;
  return ((raw % len) + len) % len;
}

export function newRotationState(): RotationState {
  return {nextIndex: 0, lastUsedAt: {}};
}

export function buildVoiceRoutes(
  keys: VoiceKey[],
  cooldown: Record<string, number>,
  state: RotationState,
  now: number,
): VoiceRoute[] {
  const len = VOICE_MODELS.length;
  const start = safeModelIndex(state.nextIndex);
  const ready: VoiceRoute[] = [];
  const resting: VoiceRoute[] = [];

  for (let i = 0; i < len; i += 1) {
    const model = VOICE_MODELS[(start + i) % len];
    const ordered = keys.map((k, idx) => ({
      k,
      idx,
      used: state.lastUsedAt[model + '@' + k.id] || 0,
    }));
    ordered.sort((a, b) => (a.used !== b.used ? a.used - b.used : a.idx - b.idx));

    for (const item of ordered) {
      const key = item.k;
      const tag = model + '@' + key.id;
      if ((cooldown[tag] || 0) > now) {
        continue;
      }
      const route: VoiceRoute = {model, id: key.id, key: key.key, tag};
      if (now - (state.lastUsedAt[tag] || 0) < VOICE_ROUTE_GAP_MS) {
        resting.push(route);
      } else {
        ready.push(route);
      }
    }
  }

  return ready.concat(resting);
}

export function markUsed(state: RotationState, tag: string, now: number): void {
  state.lastUsedAt[tag] = now;
}

export function afterSuccess(
  state: RotationState,
  model: string,
): {used: string; next: string} {
  const index = VOICE_MODELS.indexOf(model);
  if (index !== -1) {
    state.nextIndex = (index + 1) % VOICE_MODELS.length;
  }
  const safeIdx = safeModelIndex(state.nextIndex);
  return {used: model, next: VOICE_MODELS[safeIdx]};
}

export function rotationText(state: RotationState): string {
  return 'voice rotation: next is ' + VOICE_MODELS[safeModelIndex(state.nextIndex)];
}

export function wordCount(text: string): number {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).filter(Boolean).length;
}

export function isTooShort(text: string): boolean {
  const count = wordCount(text);
  if (count === 0) return false;
  return count < MIN_WORDS;
}

export function shortRetryNote(words: number): string {
  return (
    '\nYOUR LAST DRAFT WAS TOO SHORT (' +
    words +
    ' words). Write at least ' +
    RETRY_WORDS +
    ' words.'
  );
}
"""


def write(p, text):
    f = pathlib.Path(p)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(text.encode("utf-8"))
    print("wrote", p, "(%d lines)" % text.count("\n"))


def main():
    if not pathlib.Path("package.json").exists():
        print("Run this from the repo root (package.json not found).")
        sys.exit(1)
    write("src/utils/crew.ts", CREW_TS)
    write("src/utils/voiceRotation.ts", VOICE_TS)
    print("CREW PATCH OK")


if __name__ == "__main__":
    main()
