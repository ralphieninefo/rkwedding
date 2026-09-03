const directory = document.querySelector("#venueDirectory");
const directoryMessage = document.querySelector("#directoryMessage");
const directoryCount = document.querySelector("#directoryCount");
const venueSearch = document.querySelector("#venueSearch");
const logoutButton = document.querySelector("#logoutButton");
const researchDialog = document.querySelector("#researchDialog");
const researchForm = document.querySelector("#researchForm");
const researchMessage = document.querySelector("#researchMessage");
const closeResearchDialog = document.querySelector("#closeResearchDialog");
const cancelResearch = document.querySelector("#cancelResearch");
let allVenues = [];
let researchVenue = null;

const formatDate = (value) => value ? new Date(value).toLocaleString([], {dateStyle:"medium",timeStyle:"short"}) : "—";
const formatEuro = (value) => new Intl.NumberFormat([], {style:"currency",currency:"EUR",maximumFractionDigits:0}).format(value);
const formatBytes = (value) => {
  const bytes=Number(value||0); if(!bytes)return "";
  if(bytes<1024)return `${bytes} B`;
  if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/(1024*1024)).toFixed(1)} MB`;
};
const addField = (list, label, value, link) => {
  const wrap=document.createElement("div"), term=document.createElement("dt"), detail=document.createElement("dd");
  term.textContent=label;
  if (link && value) { const anchor=document.createElement("a"); anchor.href=link; anchor.target="_blank"; anchor.rel="noopener"; anchor.textContent=value; detail.append(anchor); }
  else detail.textContent=value || "—";
  wrap.append(term,detail); list.append(wrap);
};

const render = (venues) => {
  directory.replaceChildren();
  venues.forEach((venue) => {
    const card=document.createElement("article"); card.className="venue-card";
    const head=document.createElement("div"); head.className="venue-card-head";
    const identity=document.createElement("div"), name=document.createElement("h2"), location=document.createElement("p"), status=document.createElement("span");
    name.textContent=venue.name; location.className="venue-card-location"; location.textContent=[venue.region,venue.location].filter(Boolean).join(" · ") || "Region not added";
    status.className="status-pill"; status.textContent=venue.status; identity.append(name,location); head.append(identity,status);
    const meta=document.createElement("dl"); meta.className="venue-meta";
    addField(meta,"Email",venue.email,`mailto:${venue.email}`); addField(meta,"Phone",venue.phone,venue.phone?`tel:${venue.phone}`:null);
    const website=venue.website && !venue.website.startsWith("http") ? `https://${venue.website}` : venue.website;
    addField(meta,"Website",venue.website,website); addField(meta,"First email sent",formatDate(venue.sent_at));
    addField(meta,"Last response",formatDate(venue.responded_at));
    addField(meta,"Guest capacity",venue.guest_capacity); addField(meta,"Vibe",venue.vibe);
    const low=venue.price_minimum_eur||venue.price_maximum_eur, high=venue.price_maximum_eur||venue.price_minimum_eur;
    addField(meta,"90-guest estimate",low ? (low===high?formatEuro(low):`${formatEuro(low)}–${formatEuro(high)}`) : "—");
    const summary=document.createElement("p"); summary.className="venue-summary"; summary.textContent=venue.response_summary || venue.price_note || "No response information yet.";
    const details=document.createElement("p"); details.className="venue-notes"; details.textContent=[venue.price_note,venue.notes].filter(Boolean).join(" · "); details.hidden=!details.textContent;
    const research=document.createElement("section"); research.className="venue-research";
    const researchLabel=document.createElement("span"); researchLabel.textContent="Human research";
    const researchText=document.createElement("p"); researchText.textContent=venue.research_notes || "No separate research notes yet.";
    research.append(researchLabel,researchText);
    if (venue.research_source_type || venue.research_contact_name || venue.research_source_url) {
      const source=document.createElement("small");
      source.append(document.createTextNode([venue.research_source_type,venue.research_contact_name].filter(Boolean).join(" · ")));
      if (venue.research_source_url) { const link=document.createElement("a"); link.href=venue.research_source_url; link.target="_blank"; link.rel="noopener"; link.textContent=" View source ↗"; source.append(link); }
      research.append(source);
    }
    const documents=document.createElement("section"); documents.className="venue-documents";
    const documentsHead=document.createElement("div"), documentsLabel=document.createElement("span"), documentsCount=document.createElement("small");
    documentsLabel.textContent="Documents"; documentsCount.textContent=`${(venue.documents||[]).length} ${(venue.documents||[]).length===1?"file":"files"}`; documentsHead.append(documentsLabel,documentsCount); documents.append(documentsHead);
    if (!(venue.documents||[]).length) {
      const empty=document.createElement("p"); empty.className="venue-documents-empty"; empty.textContent="No Gmail attachments mirrored yet."; documents.append(empty);
    } else {
      const list=document.createElement("ul"); list.className="venue-document-list";
      venue.documents.forEach((documentItem)=>{
        const item=document.createElement("li"), info=document.createElement("div"), filename=document.createElement("strong"), context=document.createElement("small"), documentActions=document.createElement("div");
        filename.textContent=documentItem.filename; context.textContent=[documentItem.subject,formatDate(documentItem.received_at),formatBytes(documentItem.byte_size)].filter(Boolean).join(" · "); info.append(filename,context);
        const view=document.createElement("a"); view.href=documentItem.view_url; view.target="_blank"; view.rel="noopener"; view.textContent="View"; documentActions.append(view);
        if(documentItem.gmail_url){ const original=document.createElement("a"); original.href=documentItem.gmail_url; original.target="_blank"; original.rel="noopener"; original.textContent="Open in Gmail"; documentActions.append(original); }
        item.append(info,documentActions); list.append(item);
      });
      documents.append(list);
    }
    const actions=document.createElement("div"); actions.className="venue-card-actions";
    const addResearch=document.createElement("button"); addResearch.className="button button-secondary"; addResearch.type="button"; addResearch.textContent=venue.research_notes?"Edit research":"Add research";
    addResearch.addEventListener("click",()=>openResearch(venue)); actions.append(addResearch);
    if (venue.gmail_url) { const gmail=document.createElement("a"); gmail.className="button button-primary"; gmail.href=venue.gmail_url; gmail.target="_blank"; gmail.rel="noopener"; gmail.textContent="Open in Gmail"; actions.append(gmail); }
    card.append(head,meta,summary,details,research,documents,actions); directory.append(card);
  });
  directoryCount.textContent=`${venues.length} venues`; directoryMessage.hidden=venues.length>0; directory.hidden=venues.length===0;
  if (!venues.length) directoryMessage.textContent="No venues match that search.";
};

venueSearch.addEventListener("input", () => {
  const query=venueSearch.value.trim().toLocaleLowerCase();
  render(query ? allVenues.filter(v => [v.name,v.region,v.location,v.email,v.phone,v.website,v.status,v.vibe,v.guest_capacity,v.notes,v.research_notes,v.research_contact_name,v.research_source_type].some(x => String(x||"").toLocaleLowerCase().includes(query))) : allVenues);
});

const loadDirectory=()=>fetch("/api/venues").then(async response => { const result=await response.json(); if(!response.ok) throw new Error(result.detail||"Could not load venues."); allVenues=result.venues; render(allVenues); });
const openResearch=(venue)=>{ researchVenue=venue; document.querySelector("#researchDialogTitle").textContent=venue.name; researchForm.elements.source_type.value=venue.research_source_type||"Reddit"; researchForm.elements.source_url.value=venue.research_source_url||""; researchForm.elements.contact_name.value=venue.research_contact_name||""; researchForm.elements.notes.value=venue.research_notes||""; researchMessage.textContent="Research stays separate from official email and quote data."; researchDialog.showModal(); };
const closeResearch=()=>researchDialog.close();
closeResearchDialog.addEventListener("click",closeResearch); cancelResearch.addEventListener("click",closeResearch);
researchForm.addEventListener("submit",async(event)=>{ event.preventDefault(); if(!researchVenue)return; const button=event.submitter; button.disabled=true; researchMessage.textContent="Saving…"; try { const payload=Object.fromEntries(new FormData(researchForm).entries()); const response=await fetch(`/api/venues/${researchVenue.id}/research`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}); const result=await response.json(); if(!response.ok)throw new Error(result.detail||"Could not save research."); researchDialog.close(); await loadDirectory(); } catch(error){ researchMessage.textContent=error.message||"Could not save research."; } finally { button.disabled=false; } });

loadDirectory().catch(error => { directoryMessage.textContent=error.message; });

logoutButton.addEventListener("click",async()=>{ await fetch("/api/logout",{method:"POST"}); window.location.assign("/login"); });
