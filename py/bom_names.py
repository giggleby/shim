# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""HWID data web service ; pool of names for use during bulk HWID creation."""


def process_bom_names(s):
  """Return a list of HWID names, filtered for legality and upper-cased."""
  name_list = s.split()
  name_list = [x.upper() for x in name_list if len(x) <= 16 and x.isalpha()]
  return set(name_list)


#
# Parrot MP BOM names
#
# - http://en.wikipedia.org/wiki/List_of_birds_of_California
# - http://en.wikipedia.org/wiki/list_of_birds_of_hawaii
# - http://en.wikipedia.org/wiki/List_of_birds_by_common_name
# - http://en.wikipedia.org/wiki/List_of_common_fish_names
#
BOM_NAME_SET = process_bom_names("""
EAGLE
FALCON
FINCH
SPARROW
DUCK
GEESE
SWAN
PARTRIDGE
GROUSE
TURKEY
QUAIL
LOON
GREBE
ALBATROSS
SHEARWATER
PETREL
TROPICBIRD
BOOBY
GANNET
PELICAN
CORMORANT
DARTER
FRIGATEBIRD
BITTERN
HERON
EGRET
IBIS
SPOONBILL
STORK
VULTURE
OSPREY
HAWK
KITE
CARACARA
RAIL
GALLINULE
COOT
CRANE
LAPWING
PLOVER
OYSTERCATCHER
STILT
AVOCET
SANDPIPER
CURLEW
STINT
GODWIT
SNIPE
PHALAROPE
SKUA
GULL
TERN
SKIMMER
AUK
MURRE
PUFFIN
PIGEON
DOVE
LORY
PARAKEET
MACAW
CUCKOO
ROADRUNNER
ANI
OWL
NIGHTJAR
SWIFT
HUMMINGBIRD
KINGFISHER
WOODPECKER
SAPSUCKER
FLICKER
FLYCATCHER
SHRIKE
VIREO
JAY
CROW
MAGPIE
RAVEN
LARK
SWALLOW
MARTIN
CHICKADEE
TITMICE
VERDIN
BUSHTIT
NUTHATCH
TREECREEPER
WREN
DIPPER
KINGLET
MEGALURIDAE
PHYLLOSCOPIDAE
GNATCATCHER
THRUSH
BABBLER
THRASHER
STARLING
WAGTAIL
PIPIT
WAXWING
LONGSPUR
BUNTING
WARBLER
TOWHEE
JUNCO
CARDINAL
SALTATOR
GROSBEAK
BLACKBIRD
MEADOWLARK
COWBIRD
GRACKLE
ORIOLE
TINAMOU
OSTRICH
CASSOWARY
EMU
KIWI
GAMEBIRD
MALLEEFOWL
MALEO
CHACHALACA
CURASSOW
GUAN
GUINEAFOWL
BOBWHITE
PTARMIGAN
SNOWCOCK
TRAGOPAN
JUNGLEFOWL
CHICKEN
PHEASANT
PEAFOWL
WATERFOWL
SCREAMER
NENE
SHOVELTER
SHELDUCK
WIGEON
PINTAIL
MALLARD
TEAL
POCHARD
SCAUP
EIDER
SCOTER
GOLDENEYE
SMEW
MERGANSER
PENGUIN
PRION
FULMAR
CAHOW
STORMPETREL
DIVINGPETREL
FLAMINGO
OPENBILL
JABIRU
ADJUTANT
HAMMERKOP
SHOEBILL
ANHINGA
MERLIN
GYRFALCON
BUZZARD
GOSHAWK
SERIEMA
SUNBITTERN
CRAKE
SORA
SWAMPEN
TAKAHE
FINFOOT
LIMPKIN
SUNGREBE
BUTTONQUAIL
BROLGA
STONECURLEW
SHEATHBILL
IBISBILL
KILLDEER
WRYBILL
JACANA
WOODCOCK
DOWITCHER
WHIMBREL
REDSHANK
YELLOWLEGS
TATTLER
DUNLIN
RUFF
REDKNOT
PRANTINCOLE
COURSER
PRANTINCOLE
KITTIWAKE
NODDY
GUILLEMOT
SANDGROUSE
BRONZEWING
KAKAPO
KEA
COCKATOO
CORELLA
GALAH
LORIKEET
COCKATIEL
REDLORY
BLUEBONNET
ROSELLA
BUDGERIGAR
LOVEBIRD
AMAZON
HOATZIN
TURACO
KOEL
COUA
COUCAL
FROGMOUTH
OILBIRD
POTOO
NIGHTHAWK
PAURAQUE
NEEDLETAIL
HERMIT
SICKLEBILL
SABREWING
TOPAZ
PLOVERCREST
COQUETTE
STREAMERTAIL
WOODNYMPH
INCA
HILLSTAR
EMERALD
BRILLIANT
PUFFLEG
MOUSEBIRD
TROGON
QUETZAL
TOUCANET
ARACARI
TOUCAN
BARBET
TINKERBIRD
RHEA
CAPERCAILLIE
SPURFOWL
GADWALL
DIVER
SHAG
CONDOR
KESTREL
HOBBY
BATELEUR
BESRA
SPARROWHAWK
SNAKEEAGLE
HAWKEAGLE
BUSTARD
KORHAAN
KAGU
MESITE
MOORHEN
SEEDSNIPE
WOODPIGEON
QUAILDOVE
FRUITDOVE
BLUEPIGEON
IMPERIALPIGEON
RACQUETTAIL
FIGPARROT
PARROTLET
GOAWAYBIRD
EAGLEOWL
SCOPSOWL
FISHOWL
FISHINGOWL
PYGMYOWL
OWLET
POORWILL
SWIFTLET
TRAINBEARER
MOUNTAINTOUCAN
HONEYGUIDE
WRYNECK
PICULET
YELLOWNAPE
FRAMEBACK
JACAMAR
PUFFBIRD
NUNBIRD
NUNLET
BROADBILL
ASITY
SUNBIRD
PITTA
MANAKIN
SCHIFFORNIS
PLANTCUTTER
FRUITEATER
SHARPBILL
COTINGA
UMBRELLABIRD
ELAENIA
PYGMYTYRANT
TYRANNULET
TODYFLYCATCHER
SPADEBILL
PHOEBE
PEWEE
GROUNDTYRANT
MONJITA
KISKADEE
KINGBIRD
ANTBIRD
ANTWREN
ANTSHRIKE
BAREEYE
GNATEATER
GALLITO
TAPACULO
BRISTLEFRONT
ANTTHRUSH
ANTPITTA
MINER
CACHALOTE
CINCLODES
CANASTERO
HORNERO
RAYADITO
SPINETAIL
FIREWOODGATHERER
XENOPS
FOLIAGEGLEANER
WOODCREEPER
SCYTHEBILL
LYREBIRD
CATBIRD
BOWERBIRD
SCRUBBIRD
FAIRYWREN
GRASSWREN
STITCHBIRD
BELLBIRD
FRAIRBIRD
WATTLEBIRD
CHAT
BRISTLEBIRD
PARDALOTE
PILOTBIRD
FERNWREN
SCRUBWREN
WEEBILL
GERYGONE
WHITEFACE
THORNBILL
LOGRUNNER
SATINBIRD
BERRYPECKER
LONGBILL
SADDLEBACK
KOKAKO
WHIPBIRD
JEWELBABBLER
QUAILTHRUSH
BATIS
WATTLEEYE
HELMETSHRIKE
BOKMAKIERIE
BUSHSHRIKE
TCHAGRA
BOATBILL
VANGA
BUTCHERBIRD
CURRAWONG
WOODSWALLOW
IORA
BRISTLEHEAD
CICADABIRD
TRILLER
MINIVET
SITTELLA
WHISTLER
FISCAL
PEPPERSHRIKE
FIGBIRD
BELLBIRD
DRONGO
FANTAIL
ELEPAIO
MAGPIELARK
SILKTAIL
CHOUGH
PIAPIAC
JACKDAW
ROOK
APOSTLEBIRD
ASTRAPIA
PARADISE
RIFLEBIRD
ROBIN
WINTER
PICATHARTES
HYPOCOLIUS
SKYLARK
WOODLARK
CISTICOLA
PRINIA
APALIS
CAMAROPTERA
TAILORBIRD
BULBUL
GREENBUL
BERNIERIA
BRISTLEBILL
GRASSBIRD
SPINIFEXBIRD
SONGLARK
REEDWARBLER
CLIFFCHAFF
EREMOMELA
CROMBEC
BLACKCAP
WHITETHROAT
ILLADOPSIS
MESIA
FULVETTA
SIBIA
YUHINA
PARROTBILL
ROCKJUMPER
SILVEREYE
GOLDCREST
AHOLEHOLE
ALBACORE
ALEWIFE
ALFONSINO
ALLIGATORFISH
AMAGO
ANCHOVY
ANEMONEFISH
ANGELFISH
ANGLER
ANGLERFISH
ARAPAIMA
ARCHERFISH
ARMORHEAD
AROWANA
ARUANA
AYU
ALOOH
BANDFISH
BANGO
BANGUS
BARB
BARBEL
BARFISH
BARRACUDA
BARRACUDINA
BARRAMUNDI
BARRELEYE
BASS
BASSLET
BATFISH
BEACHSALMON
BEARDFISH
BETTA
BICHIR
BIGEYE
BIGSCALE
BILLFISH
BITTERLING
BLACKCHIN
BLACKFISH
BLACKSMELT
BLEAK
BLENNY
BLOBFISH
BLOWFISH
BLUEFISH
BLUEGILL
BOAFISH
BOARFISH
BOCACCIO
BOGA
BONEFISH
BONITO
BONNETMOUTH
BONYTONGUE
BOWFIN
BOXFISH
BREAM
BRISTLEMOUTH
BROTULA
BUFFALOFISH
BULLHEAD
BURBOT
BURI
BUTTERFLYFISH
CANDIRU
CANDLEFISH
CAPELIN
CARDINALFISH
CARP
CARPETSHARK
CARPSUCKER
CATALUFA
CATFISH
CATLA
CAVEFISH
CEPALIN
CHAR
CHIMAERA
CHERUBFISH
CHUB
CHUBSUCKER
CICHLID
CISCO
CLINGFISH
CLOWNFISH
COBBLER
COBIA
COD
CODLET
CODLING
COELACANTH
COFFINFISH
COLEY
COMBFISH
CORNETFISH
COWFISH
CRAPPIE
CRESTFISH
CROAKER
CUCHIA
CUSKFISH
CUTLASSFISH
DAB
DACE
DAMSELFISH
DANIO
DARTER
DARTFISH
DEALFISH
DEMOISELLE
DEVARIO
DHUFISH
DISCUS
DOGFISH
DORAB
DORADO
DORY
DOTTYBACK
DRAGONET
DRAGONFISH
DRIFTFISH
DRUM
DUCKBILL
EEL
EELBLENNY
EELPOUT
ELASMOBRANCH
ELVER
EMPEROR
ESCOLAR
EULACHON
FANGTOOTH
FEATHERBACK
FIERASFER
FILEFISH
FINGERFISH
FIREFISH
FLAGBLENNY
FLAGFIN
FLAGFISH
FLAGTAIL
FLATFISH
FLATHEAD
FLIER
FLOUNDER
FLYINGFISH
FOOTBALLFISH
FROGFISH
GAR
GARIBALDI
GARPIKE
GHOUL
GIANTTAIL
GIBBERFISH
GLASSFISH
GOATFISH
GOBY
GOLDEYE
GOLDFISH
GOMBESSA
GOOSEFISH
GOURAMIE
GRAVELDIVER
GRAYLING
GREENEYE
GREENLING
GRENADIER
GRIDEYE
GROUPER
GRUNION
GRUNT
GRUNTER
GUDGEON
GUITARFISH
GULPER
GUNNEL
GUPPY
GURNARD
HADDOCK
HAGFISH
HAIRTAIL
HAKE
HALFBEAK
HALFMOON
HALIBUT
HALOSAUR
HAMLET
HAMMERJAW
HANDFISH
HATCHETFISH
HAWKFISH
HERRING
HOKI
HORSEFISH
HOUNDSHARK
HUCHEN
HUSSAR
ICEFISH
IDE
ILISHA
INANGA
INCONNU
JACK
JACKFISH
JAVELIN
JAWFISH
JEWELFISH
JEWFISH
JELLA
KAHAWAI
KALUGA
KANYU
KELPFISH
KILLIFISH
KINGFISH
KNIFEFISH
KNIFEJAW
KOI
KOKANEE
KOKOPU
LADYFISH
LAGENA
LAMPFISH
LAMPREY
LANCETFISH
LANTERNFISH
LEAFFISH
LEATHERJACKET
LENOK
LIGHTFISH
LIGHTHOUSEFISH
LIMIA
LING
LIVEBEARER
LIZARDFISH
LOACH
LONGFIN
LOOSEJAW
LOUVAR
LUDERICK
LUMPSUCKER
LUNGFISH
LUTEFISK
LYRETAIL
MACKEREL
MADTOM
MAHSEER
MANEFISH
MARBLEFISH
MARLIN
MEDAKA
MEDUSAFISH
MENHADEN
MIDSHIPMAN
MILKFISH
MINNOW
MOJARRA
MOLA
MOLLY
MONKFISH
MOONEYE
MOONFISH
MORA
MORWONG
MOSQUITOFISH
MOUTHBROODER
MRIGAL
MUDFISH
MUDMINNOW
MUDSKIPPER
MUDSUCKER
MULLET
MUMMICHOG
MUSKELLUNGE
NASE
NEEDLEFISH
NOODLEFISH
NURSERYFISH
OARFISH
OILFISH
OLDWIFE
OPAH
OPALEYE
PADDLEFISH
PANGA
PAPERBONE
PARROTFISH
""")
