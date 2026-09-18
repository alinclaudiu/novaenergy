# Întrebări frecvente — Nova Energy România

---

## Ce face, pe scurt, integrarea?

Aduce în Home Assistant datele contului tău Nova Power & Gas: soldul, facturile, plățile, contractele și indexul contoarelor. Le poți pune pe dashboard, le poți folosi în automatizări și le vezi în istoric.

---

## Trebuie să plătesc ceva? Am nevoie de o cheie?

Nu. Integrarea este gratuită, sub licență MIT, și nu conține niciun mecanism de activare. Toate entitățile sunt disponibile imediat după instalare, pentru oricine.

---

## Cum o instalez?

Prin HACS, ca repository custom, sau copiind manual folderul `custom_components/novaenergy/`. Pașii compleți sunt în [SETUP.md](SETUP.md).

---

## Am mai multe conturi Nova. Le pot vedea pe toate?

Da. Dacă ele sunt conturi asociate aceluiași cont de autentificare, integrarea le descoperă singură și te lasă să alegi pe care să le monitorizezi. Fiecare cont primește propriile dispozitive și senzori.

Dacă ai conturi de autentificare complet separate, adaugă integrarea de mai multe ori, o dată pentru fiecare adresă de email.

---

## De ce am două dispozitive pentru același cont?

Pentru că ai și gaz, și energie electrică pe acel cont. Fiecare utilitate are contract propriu, contor propriu și facturi proprii, așa că primește un dispozitiv separat: `Nova Energy (3047398) Gaz` și `Nova Energy (3047398) Energie Electrică`.

---

## Cât de des se actualizează datele?

Implicit la 6 ore. Poți schimba intervalul din **Configurare** (⚙️), cu minimum 5 minute.

Nu merită să cobori mult intervalul: facturile se emit lunar, iar soldul se schimbă de câteva ori pe lună. Interogările dese nu aduc informație nouă, doar trafic.

---

## Un senzor arată „indisponibil". E o eroare?

De cele mai multe ori, nu. Înseamnă că API-ul nu a întors valoarea respectivă în acest ciclu.

Integrarea preferă intenționat `unavailable` în locul lui `0`: un zero fals ar intra în statistici și ți-ar strica graficele pe termen lung. La următoarea actualizare reușită, senzorul revine singur.

---

## De ce nu am senzorul de sold prosumator?

Pentru că acel cont nu are sold de prosumator. Senzorul se creează doar acolo unde API-ul întoarce efectiv valoarea — nu are rost o entitate care arată permanent „nimic".

---

## Am schimbat contorul. Ce se întâmplă?

Senzorii de index sunt identificați prin seria contorului, deci apare o entitate nouă pentru contorul nou. Cea veche rămâne, cu istoricul ei, și devine indisponibilă. O poți șterge din interfață când nu-ți mai trebuie.

---

## Pot trimite autocitirea prin integrare?

Nu în versiunea 1.x — deocamdată integrarea doar citește. Trimiterea autocitirilor scrie în contul tău real, așa că primește o versiune separată, gândită și testată pentru asta.

---

## De ce sumele apar cu punct și virgulă invers față de engleză?

Pentru că respectă convenția românească: punctul separă miile, virgula zecimalele. `1.234,56 lei` înseamnă o mie două sute treizeci și patru de lei și cincizeci și șase de bani.

---

## Ce înseamnă „Factură restantă: Da"?

Că există cel puțin o factură neachitată, cu sumă rămasă de plată. În atribute găsești totalul restant, câte facturi sunt și scadența celei mai îndepărtate.

---

## Arhiva de facturi îmi arată mai puține facturi decât știu că am.

Arhiva numără doar facturile din **anul curent**. O factură emisă în decembrie anul trecut nu apare în arhiva din ianuarie anul acesta.

---

## Trebuie să repornesc Home Assistant după ce schimb setările?

Nu. Modificările făcute din **Configurare** (⚙️) reîncarcă integrarea automat. Repornirea e necesară doar la instalare și la actualizarea versiunii.

---

## Trebuie să șterg și să readaug integrarea la actualizare?

Nu. Actualizezi prin HACS, repornești Home Assistant, iar entitățile și istoricul rămân neatinse.

---

## Unde se păstrează parola mea?

În stocarea internă Home Assistant, criptată, ca la orice altă integrare. Nu apare în loguri nici la nivel de debug, nu apare în raportul de diagnostic și nu pleacă nicăieri în afară de serverele Nova.

---

## Pot trimite raportul de diagnostic într-un issue public?

Da. Raportul maschează adresa de email și nu conține parola, tokenul sau datele personale din răspunsurile API. Conține starea conturilor, câte facturi și contracte există și lista de senzori — exact ce trebuie pentru diagnosticare.

---

## Integrarea e oficială, de la Nova?

Nu. Este un proiect independent, scris de la zero, fără nicio legătură cu compania. Folosește aceleași endpoint-uri ca aplicația web de client.

---

## Ceva nu merge. Ce fac?

Începe cu [DEBUG.md](DEBUG.md): explică cum activezi logurile detaliate, ce înseamnă mesajele și ce e normal să vezi. Dacă tot nu se lămurește, deschide un [issue](https://github.com/alinclaudiu/novaenergy/issues) cu logurile și raportul de diagnostic.
