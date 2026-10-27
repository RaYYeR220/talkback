"""Name pools for the fictional league.

Every club, town and person here is invented. BANNED_CLUB_NAMES lists real
top-flight clubs so the generator can prove it never reuses one.
"""

LEAGUE_NAME = "The Meridian League"
SEASON = "2026/27"

# (club name, short code, home town, primary colour, secondary colour)
CLUBS: list[tuple[str, str, str, str, str]] = [
    ("Ashcombe Rovers", "ASH", "Ashcombe", "#1f4e9c", "#f2f2f2"),
    ("Calder Vale", "CAL", "Calderford", "#7a1f2b", "#e8c547"),
    ("Ironmouth Athletic", "IRO", "Ironmouth", "#2b2b2b", "#d9a33b"),
    ("Westmarsh Town", "WES", "Westmarsh", "#0f6b4f", "#ffffff"),
    ("Kestrel Bay Wanderers", "KES", "Kestrel Bay", "#3a7fc1", "#0d2340"),
    ("Thornwick Albion", "THO", "Thornwick", "#c8102e", "#ffffff"),
    ("Fenmoor Harriers", "FEN", "Fenmoor", "#f28c28", "#1b1b1b"),
    ("Redcastle United", "RED", "Redcastle", "#b31b1b", "#0b1f3a"),
    ("Saltmere City", "SAL", "Saltmere", "#6cace4", "#ffffff"),
    ("Brackenridge Rangers", "BRA", "Brackenridge", "#4a2c6d", "#f5d000"),
    ("Oakhollow Forest", "OAK", "Oakhollow", "#355e3b", "#f0e6d2"),
    ("Glenmarrow Athletic", "GLE", "Glenmarrow", "#004d6d", "#f7b500"),
    ("Pellbridge Town", "PEL", "Pellbridge", "#ffd100", "#1a1a1a"),
    ("Merrowport", "MER", "Merrowport", "#00838f", "#ffffff"),
    ("Halverton Wanderers", "HAL", "Halverton", "#8b5a2b", "#ffffff"),
    ("Stonebeck Athletic", "STO", "Stonebeck", "#5b6770", "#e03c31"),
    ("Wrenford Albion", "WRE", "Wrenford", "#d7263d", "#1b998b"),
    ("Copperhill United", "COP", "Copperhill", "#b87333", "#0c2d48"),
    ("Eastlyn Town", "EAS", "Eastlyn", "#2e3192", "#ec1c24"),
    ("Hollowmere Rovers", "HOL", "Hollowmere", "#111111", "#7fc241"),
]

BANNED_CLUB_NAMES: list[str] = [
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Burnley", "Cardiff",
    "Chelsea", "Crystal Palace", "Everton", "Fulham", "Huddersfield", "Hull City", "Ipswich",
    "Leeds", "Leicester", "Liverpool", "Luton", "Manchester City", "Manchester United",
    "Middlesbrough", "Newcastle", "Norwich", "Nottingham Forest", "Sheffield United",
    "Southampton", "Stoke City", "Sunderland", "Swansea", "Tottenham", "Watford",
    "West Bromwich", "West Ham", "Wolverhampton",
]

FIRST_NAMES: list[str] = [
    "Aarav", "Abdou", "Adebayo", "Adrian", "Ahmed", "Aidan", "Akira", "Alejandro", "Alexei",
    "Alfie", "Amadou", "Anders", "Andile", "Anton", "Arlo", "Arnav", "Bastian", "Benedikt",
    "Bilal", "Bram", "Callum", "Caio", "Cedric", "Chidi", "Cian", "Cosmin", "Dario", "Darnell",
    "Davor", "Declan", "Diego", "Dimitri", "Duarte", "Eamon", "Elias", "Emeka", "Enzo", "Esteban",
    "Ewan", "Farouk", "Felix", "Filip", "Finlay", "Florian", "Gael", "Gideon", "Goran", "Hamza",
    "Hassan", "Henrik", "Hugo", "Ibrahima", "Idris", "Ilya", "Isaac", "Ivo", "Jakub", "Jamal",
    "Janek", "Jarvis", "Joaquin", "Jonas", "Jude", "Kai", "Kamil", "Karim", "Kasper", "Kenji",
    "Kofi", "Kwame", "Laszlo", "Lennart", "Leon", "Lorcan", "Luca", "Lukas", "Malik", "Mamadou",
    "Marek", "Mateo", "Matias", "Milan", "Moussa", "Nadir", "Nikola", "Nils", "Obi", "Oisin",
    "Olaf", "Omar", "Oskar", "Pablo", "Pavel", "Quentin", "Rafael", "Rasmus", "Reuben", "Rhys",
    "Rio", "Rory", "Rui", "Ruben", "Samir", "Sander", "Santiago", "Seamus", "Sekou", "Sergei",
    "Silas", "Soren", "Stellan", "Tariq", "Teodor", "Theo", "Tiago", "Tobias", "Tomas", "Toby",
    "Tunde", "Umar", "Valentin", "Viktor", "Wiktor", "Xavi", "Yannick", "Yaw", "Yusuf", "Zane",
    "Zoran",
]

LAST_NAMES: list[str] = [
    "Abara", "Achterberg", "Adewale", "Agbaje", "Aldana", "Almqvist", "Amankwah", "Andrade",
    "Arkwright", "Asante", "Balogun", "Barraclough", "Bekele", "Bellweather", "Benneker", "Blackwood",
    "Bonfim", "Brannigan", "Brzezinski", "Calloway", "Carvalhal", "Castellanos", "Chikwanda",
    "Corcoran", "Dalgaard", "Dankwa", "Delacroix", "Desmarais", "Dobrev", "Drummond", "Duvall",
    "Eberhardt", "Ekwueme", "Esposito", "Falconer", "Fairweather", "Ferreirinha", "Fitzgerald",
    "Gallacher", "Garrido", "Gathercole", "Gerrity", "Gonzaga", "Grimshaw", "Halloran", "Haverkamp",
    "Hendricks", "Holloway", "Ibekwe", "Iglesias", "Ivanovski", "Jankowski", "Jessop", "Joubert",
    "Kaczmarek", "Kallstrom", "Kasprzak", "Kettering", "Kinsella", "Kovalenko", "Lacombe",
    "Lindqvist", "Lombardo", "Loughran", "Madugu", "Magnusson", "Malakai", "Marchetti",
    "Mbatha", "McAllister", "Mendonca", "Mensah", "Moravec", "Muldoon", "Nakagawa", "Nascimento",
    "Ndiaye", "Novotny", "Nwachukwu", "Oakenfold", "Obradovic", "Okafor", "Olasunkanmi",
    "Ostergaard", "Pacheco", "Palacios", "Pemberton", "Petrakis", "Pinheiro", "Quarshie",
    "Rademeyer", "Rademacher", "Ravenscroft", "Rookhaven", "Rosales", "Ruzicka", "Sadiq",
    "Salgado", "Sandoval", "Sarr", "Schellenberg", "Sefolosha", "Sheridan", "Silvano", "Sorensen",
    "Strachan", "Szymanski", "Tavener", "Tembo", "Thorsen", "Tomasevic", "Tchoula", "Urquhart",
    "Underhill", "Valdivieso", "Vandersloot", "Varga", "Vasquez", "Wainwright", "Westergaard",
    "Whitlock", "Wojcik", "Yeboah", "Zamorano-Pell", "Zielinski", "Zubiri", "Okonjo", "Halvorsen",
]

MANAGER_FIRST: list[str] = [
    "Graham", "Rui", "Sten", "Marta", "Konrad", "Ayo", "Fergal", "Ingrid", "Lucien", "Desmond",
    "Paulo", "Helga", "Neil", "Beatriz", "Viggo", "Ruth", "Marco", "Selim", "Hannah", "Tadeusz",
]
