// Mainstream-Burgundy control set — seller list = Lea & Sandeman's live In Bond
// Burgundy, captured 2026-09-21T14:37:59Z. One entry per distinct wine/vintage/format.
//
// Each line: [id, vintage, pack, ml, requiredTokens, excludedTokens, lsPriceGBP]
// A merchant record matches only if its normalised title contains EVERY required
// token, NONE of the excluded tokens, and has the same vintage, pack and bottle ml.
// Deliberately strict: a missed join understates depth (safe); a false join
// overstates it (unsafe). Every match is then verified by eye.
const LINES = [
 ["L01",2022,6,750,["barraud","crays"],[],150],
 ["L02",2022,6,750,["barraud","sur la roche"],[],150],
 ["L03",2022,6,750,["barraud","marechaude"],[],150],
 ["L04",2021,6,750,["rossignol","chevrets"],[],490],
 ["L05",2021,6,750,["rossignol","roncerets"],[],550],
 ["L06",2021,6,750,["moreau","naudet","montmains"],[],230],
 ["L07",2021,12,750,["tribut","beauroy"],[],370],
 ["L08",2021,6,750,["lignier","michelot","mazoyeres"],[],1250],
 ["L09",2021,6,750,["germain","morgeot"],[],435],
 ["L10",2021,6,750,["clerget","echezeaux"],["grands"],795],
 ["L11",2021,6,750,["joseph","colin","compendium"],[],175],
 ["L12",2021,6,750,["joseph","colin","chateniere"],[],300],
 ["L13",2021,6,750,["joseph","colin","oratorium"],[],280],
 ["L14",2020,6,750,["clerget","chambolle","charmes"],[],390],
 ["L15",2020,3,1500,["courcel","clos","epenots"],[],480],
 ["L16",2020,3,750,["dugat","py","lavaux"],[],1000],
 ["L17",2020,6,750,["anne","gros","combe","orveau"],[],600],
 ["L18",2020,3,750,["anne","gros","maupertui"],[],750],
 ["L19",2020,6,750,["thibault","liger","vougeot"],[],780],
 ["L20",2020,6,750,["thibault","liger","reas"],[],420],
 ["L21",2020,6,750,["mugneret","gibourg","vosne"],["1er","premier","grand cru","echezeaux","chambertin","chaumes","suchots"],1200],
 ["L22",2020,6,750,["rossignol","roncerets"],[],485],
 ["L23",2020,6,750,["drouhin","puligny"],["1er","premier","folatieres","garenne","pucelles","chevalier","batard","combettes","caillerets","referts"],310],
 ["L24",2020,6,750,["anne","gros","bourgogne","blanc"],[],210],
 ["L25",2020,12,750,["moreau","naudet","tonnerre"],[],400],
 ["L26",2020,12,750,["moreau","naudet","vaillons"],[],335],
 ["L27",2020,12,750,["tribut","beauroy"],[],505],
 ["L28",2020,6,750,["dugat","py","levriere"],[],750],
 ["L29",2020,6,750,["germain","morgeot"],[],550],
 ["L30",2020,6,750,["thibault","liger","les saint georges"],[],600],
 ["L31",2020,6,750,["dugat","py","coeur","roy"],[],675],
 ["L32",2020,6,750,["joseph","colin","compendium"],[],195],
 ["L33",2020,6,750,["joseph","colin","chassagne"],["1er","premier","caillerets","morgeot","chenevottes","vergers","maltroie"],280],
 ["L34",2020,6,750,["joseph","colin","caillerets"],[],510],
 ["L35",2020,6,750,["thibault","liger","belair","corton","roi"],[],850],
 ["L36",2019,6,750,["courcel","clos","epenots"],[],600],
 ["L37",2019,6,750,["dugat","py","halinard"],[],275],
 ["L38",2019,3,750,["dugat","py","lavaux"],[],695],
 ["L39",2019,6,750,["faiveley","damodes"],[],395],
 ["L40",2019,6,750,["anne","gros","combe","orveau"],[],630],
 ["L41",2019,6,750,["thibault","liger","belair","corvee","villy"],[],180],
 ["L42",2019,6,750,["thibault","liger","belair","charmotte"],[],450],
 ["L43",2019,6,750,["mugneret","gibourg","vosne"],["1er","premier","grand cru","echezeaux","chambertin","chaumes","suchots"],1275],
 ["L44",2019,6,750,["jean","marc","boillot","referts"],[],520],
 ["L45",2019,6,750,["anne","gros","bourgogne","blanc"],[],200],
 ["L46",2019,6,750,["remi","jobard","genevrieres"],[],695],
 ["L47",2019,6,750,["lignier","michelot","faconnieres"],[],420],
 ["L48",2019,6,750,["stephane","magnien","chambolle","vieilles"],[],240],
 ["L49",2019,6,750,["joseph","colin","caillerets"],[],540],
 ["L50",2019,6,750,["dugat","py","monthelie"],[],350],
 ["L51",2018,6,750,["courcel","clos","epenots"],[],510],
 ["L52",2018,6,750,["clos des lambrays"],[],1200],
 ["L53",2018,6,750,["lambrays","loups"],[],500],
 ["L54",2018,6,750,["remi","jobard","genevrieres"],[],650],
 ["L55",2018,12,750,["moreau","naudet","forets"],[],450],
 ["L56",2018,6,750,["moreau","naudet","valmur"],[],400],
 ["L57",2018,12,750,["lamy","chateniere"],[],1000],
 ["L58",2018,12,750,["huguenot","perdrix"],[],320],
 ["L59",2018,12,750,["raquillet","naugues"],[],348],
 ["L60",2018,6,750,["dugat","py","corbeaux"],[],1500],
 ["L61",2017,6,750,["faiveley","damodes"],[],445],
 ["L62",2017,6,750,["faiveley","gevrey","vieilles"],["1er","premier","cazetiers","combe","lavaux","corbeaux"],270],
 ["L63",2016,6,750,["courcel","clos","epenots"],[],550],
 ["L64",2016,6,1500,["courcel","clos","epenots"],[],1120],
 ["L65",2015,1,3000,["courcel","clos","epenots"],[],460],
 ["L66",2015,6,750,["courcel","clos","epenots"],[],690],
 ["L67",2015,6,1500,["courcel","clos","epenots"],[],1250],
 ["L68",2015,6,750,["clos des lambrays"],[],1300],
 ["L69",2014,6,750,["courcel","clos","epenots"],[],450],
 ["L70",2011,6,750,["maume","mazis"],[],595],
];

function norm(s){
  return (s||"").toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g,"")
    .replace(/\bst\b\.?/g,"saint").replace(/[^a-z0-9 ]+/g," ").replace(/\s+/g," ").trim();
}
function matchLine(line, title, vintage, pack, ml){
  const [id,v,p,m,req,exc] = line;
  if(Number(vintage)!==v || Number(pack)!==p || Number(ml)!==m) return false;
  const t = " "+norm(title)+" ";
  return req.every(k => t.includes(" "+norm(k)+" "))
      && !exc.some(k => t.includes(" "+norm(k)+" "));
}
